from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Awaitable, Callable, Literal
from urllib.parse import quote

import httpx

from wikimedia_search.resolver import WIKIMEDIA_USER_AGENT
from wikimedia_search.static_targets import StaticTargetRecord

StaticBuildStepId = Literal[
    "article_identity",
    "article_parse",
    "article_revisions",
    "article_authorship",
    "pageviews_human",
    "pageviews_mobile_web",
    "pageviews_mobile_app",
    "pageviews_spider",
    "pageviews_automated",
    "traffic_incoming",
    "traffic_outgoing",
    "editor_summary",
    "article_claims",
    "claim_sources",
    "wikidata_entity",
    "google_trends",
    "google_news",
]


class StaticBuildStepError(Exception):
    """Raised when a static target build step cannot complete."""


def stuck_after_fetch(*, fetched: str, stuck_at: str, next_fix: str) -> StaticBuildStepError:
    return StaticBuildStepError(
        f"Fetched {fetched}; stuck at {stuck_at}. Next fix: {next_fix}."
    )


@dataclass(frozen=True)
class StaticBuildStepResult:
    step_id: str
    status: Literal["success"]
    message: str


def encoded_title(target: StaticTargetRecord) -> str:
    return quote(target.title_slug, safe="")


def pageview_dates() -> tuple[str, str]:
    today = date.today()
    start = today - timedelta(days=90)
    return start.strftime("%Y%m%d"), today.strftime("%Y%m%d")


def assert_mediawiki_response(data: dict) -> None:
    if "error" in data:
        error = data["error"]
        raise StaticBuildStepError(error.get("info") or error.get("code") or "MediaWiki API error.")


async def get_json(client: httpx.AsyncClient, url: str, *, params: dict | None = None) -> dict:
    response = await client.get(url, params=params)
    response.raise_for_status()
    data = response.json()

    if not isinstance(data, dict):
        raise StaticBuildStepError("API response was not a JSON object.")

    return data


async def run_article_identity(target: StaticTargetRecord, client: httpx.AsyncClient) -> StaticBuildStepResult:
    metadata = target.article_metadata
    raise stuck_after_fetch(
        fetched=(
            f"MediaWiki identity for {metadata.canonical_title}: page_id={metadata.page_id}, "
            f"namespace={metadata.namespace}, wikidata_qid={metadata.wikidata_qid or 'none'}"
        ),
        stuck_at="database persistence",
        next_fix="write or upsert targets, w_articles, and the w_articles-to-wdata_items link in Cloud SQL",
    )


async def run_article_parse(target: StaticTargetRecord, client: httpx.AsyncClient) -> StaticBuildStepResult:
    data = await get_json(
        client,
        f"https://{target.article_metadata.host}/w/api.php",
        params={
            "action": "parse",
            "page": target.title_slug,
            "prop": "sections|categories|links|externallinks|templates|images|revid|displaytitle",
            "formatversion": "2",
            "format": "json",
            "origin": "*",
        },
    )
    assert_mediawiki_response(data)
    parsed = data.get("parse", {})
    sections = len(parsed.get("sections", []))
    categories = len(parsed.get("categories", []))
    links = len(parsed.get("links", []))
    external_links = len(parsed.get("externallinks", []))
    templates = len(parsed.get("templates", []))
    images = len(parsed.get("images", []))
    raise stuck_after_fetch(
        fetched=(
            "MediaWiki parse payload "
            f"revid={parsed.get('revid', 'unknown')}, sections={sections}, "
            f"categories={categories}, links={links}, external_links={external_links}, "
            f"templates={templates}, images={images}"
        ),
        stuck_at="normalization and persistence",
        next_fix=(
            "map parse JSON into w_article_sections, w_article_links, target_sources, "
            "w_article_claims_sources, and citation extraction from article markup"
        ),
    )


async def run_article_revisions(target: StaticTargetRecord, client: httpx.AsyncClient) -> StaticBuildStepResult:
    data = await get_json(
        client,
        f"https://{target.article_metadata.host}/w/api.php",
        params={
            "action": "query",
            "prop": "revisions",
            "titles": target.title_slug,
            "rvprop": "ids|timestamp|user",
            "rvlimit": "500",
            "format": "json",
            "formatversion": "2",
            "origin": "*",
        },
    )
    assert_mediawiki_response(data)
    pages = data.get("query", {}).get("pages", [])
    revisions = pages[0].get("revisions", []) if pages else []
    raise stuck_after_fetch(
        fetched=f"{len(revisions)} MediaWiki revision records with ids, timestamps, and editor names",
        stuck_at="revision normalization and persistence",
        next_fix="write w_article_revisions rows and resolve revision editor names into w_editors records",
    )


async def run_pageviews(
    target: StaticTargetRecord,
    client: httpx.AsyncClient,
    *,
    access: str,
    agent: str,
    step_id: str,
) -> StaticBuildStepResult:
    start, end = pageview_dates()
    project = f"{target.lang}.wikipedia.org"
    data = await get_json(
        client,
        (
            "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
            f"{project}/{access}/{agent}/{encoded_title(target)}/daily/{start}/{end}"
        ),
    )
    items = data.get("items", [])
    raise stuck_after_fetch(
        fetched=(
            f"{len(items)} pageview points for project={project}, access={access}, "
            f"agent={agent}, range={start}-{end}"
        ),
        stuck_at="pageview normalization and persistence",
        next_fix="write static article view rows into w_article_views with target_id, access, agent, date, and views",
    )


async def run_traffic(
    target: StaticTargetRecord,
    client: httpx.AsyncClient,
    *,
    direction: Literal["sources", "destinations"],
    step_id: str,
) -> StaticBuildStepResult:
    data = await get_json(
        client,
        (
            f"https://wikinav.wmcloud.org/api/v1/{target.lang}/"
            f"{encoded_title(target)}/{direction}/latest"
        ),
        params={
            "start": "1",
            "limit": "500",
            "sort": "desc",
        },
    )
    results = data.get("results", [])
    month = data.get("month", "latest month")
    raise stuck_after_fetch(
        fetched=f"{len(results)} Wikinav {direction} records for month={month}",
        stuck_at="traffic normalization and persistence",
        next_fix=(
            "write w_article_traffic rows preserving source fields month, title, and views; "
            "derive direction, title_type, and optional url"
        ),
    )


async def run_editor_summary(target: StaticTargetRecord, client: httpx.AsyncClient) -> StaticBuildStepResult:
    data = await get_json(
        client,
        f"https://{target.article_metadata.host}/w/api.php",
        params={
            "action": "query",
            "prop": "revisions",
            "titles": target.title_slug,
            "rvprop": "ids|timestamp|user",
            "rvlimit": "500",
            "format": "json",
            "formatversion": "2",
            "origin": "*",
        },
    )
    assert_mediawiki_response(data)
    pages = data.get("query", {}).get("pages", [])
    revisions = pages[0].get("revisions", []) if pages else []
    editors = {revision.get("user") for revision in revisions if revision.get("user")}
    raise stuck_after_fetch(
        fetched=f"{len(revisions)} revision records containing {len(editors)} distinct editor names",
        stuck_at="editor analysis persistence",
        next_fix="write w_editors and w_article_editors summary rows, including edit counts and stewardship signals",
    )


async def run_wikidata_entity(target: StaticTargetRecord, client: httpx.AsyncClient) -> StaticBuildStepResult:
    qid = target.article_metadata.wikidata_qid

    if not qid:
        raise StaticBuildStepError(
            "Fetched article metadata; stuck at Wikidata lookup because this article declares no wikibase_item pageprop. "
            "Next fix: record a nullable w_articles.wikidata_item_id state instead of treating absence as success."
        )

    data = await get_json(
        client,
        "https://www.wikidata.org/w/api.php",
        params={
            "action": "wbgetentities",
            "ids": qid,
            "props": "labels|descriptions|sitelinks|claims",
            "languages": "en",
            "format": "json",
            "origin": "*",
        },
    )
    assert_mediawiki_response(data)
    entity = data.get("entities", {}).get(qid, {})
    claims = len(entity.get("claims", {}))
    sitelinks = len(entity.get("sitelinks", {}))
    labels = len(entity.get("labels", {}))
    descriptions = len(entity.get("descriptions", {}))
    raise stuck_after_fetch(
        fetched=(
            f"Wikidata entity {qid}: labels={labels}, descriptions={descriptions}, "
            f"sitelinks={sitelinks}, claim_groups={claims}"
        ),
        stuck_at="Wikidata normalization and persistence",
        next_fix="write wdata_items, link w_articles.wikidata_item_id, and persist selected labels, sitelinks, and claims",
    )


async def run_not_implemented(step_id: str, message: str) -> StaticBuildStepResult:
    raise StaticBuildStepError(message)


StepRunner = Callable[[StaticTargetRecord, httpx.AsyncClient], Awaitable[StaticBuildStepResult]]


async def run_article_authorship(target: StaticTargetRecord, client: httpx.AsyncClient) -> StaticBuildStepResult:
    return await run_not_implemented(
        "article_authorship",
        "WikiWho text-authorship connector is not implemented yet.",
    )


async def run_article_claims(target: StaticTargetRecord, client: httpx.AsyncClient) -> StaticBuildStepResult:
    return await run_not_implemented(
        "article_claims",
        "Article claims and argument extraction is not implemented yet.",
    )


async def run_claim_sources(target: StaticTargetRecord, client: httpx.AsyncClient) -> StaticBuildStepResult:
    return await run_not_implemented(
        "claim_sources",
        "Claim-to-source mapping is not implemented yet.",
    )


async def run_google_trends(target: StaticTargetRecord, client: httpx.AsyncClient) -> StaticBuildStepResult:
    return await run_not_implemented(
        "google_trends",
        "Google Trends connector is not configured yet.",
    )


async def run_google_news(target: StaticTargetRecord, client: httpx.AsyncClient) -> StaticBuildStepResult:
    return await run_not_implemented(
        "google_news",
        "Google News connector is not configured yet.",
    )


STATIC_BUILD_STEP_RUNNERS: dict[str, StepRunner] = {
    "article_identity": run_article_identity,
    "article_parse": run_article_parse,
    "article_revisions": run_article_revisions,
    "article_authorship": run_article_authorship,
    "pageviews_human": lambda target, client: run_pageviews(
        target,
        client,
        access="all-access",
        agent="user",
        step_id="pageviews_human",
    ),
    "pageviews_mobile_web": lambda target, client: run_pageviews(
        target,
        client,
        access="mobile-web",
        agent="user",
        step_id="pageviews_mobile_web",
    ),
    "pageviews_mobile_app": lambda target, client: run_pageviews(
        target,
        client,
        access="mobile-app",
        agent="user",
        step_id="pageviews_mobile_app",
    ),
    "pageviews_spider": lambda target, client: run_pageviews(
        target,
        client,
        access="all-access",
        agent="spider",
        step_id="pageviews_spider",
    ),
    "pageviews_automated": lambda target, client: run_pageviews(
        target,
        client,
        access="all-access",
        agent="automated",
        step_id="pageviews_automated",
    ),
    "traffic_incoming": lambda target, client: run_traffic(
        target,
        client,
        direction="sources",
        step_id="traffic_incoming",
    ),
    "traffic_outgoing": lambda target, client: run_traffic(
        target,
        client,
        direction="destinations",
        step_id="traffic_outgoing",
    ),
    "editor_summary": run_editor_summary,
    "article_claims": run_article_claims,
    "claim_sources": run_claim_sources,
    "wikidata_entity": run_wikidata_entity,
    "google_trends": run_google_trends,
    "google_news": run_google_news,
}


async def run_static_build_step(target: StaticTargetRecord, step_id: str) -> StaticBuildStepResult:
    runner = STATIC_BUILD_STEP_RUNNERS.get(step_id)

    if not runner:
        raise StaticBuildStepError("Unknown static build step.")

    async with httpx.AsyncClient(
        headers={"User-Agent": WIKIMEDIA_USER_AGENT},
        timeout=20.0,
    ) as client:
        return await runner(target, client)
