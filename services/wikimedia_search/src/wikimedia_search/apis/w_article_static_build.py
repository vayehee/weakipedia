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
    return StaticBuildStepResult(
        step_id="article_identity",
        status="success",
        message=(
            f"Resolved {metadata.canonical_title} as page {metadata.page_id}"
            f" on {metadata.host}."
        ),
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
    links = len(parsed.get("links", []))
    return StaticBuildStepResult(
        step_id="article_parse",
        status="success",
        message=f"Parsed article structure with {sections} sections and {links} internal links.",
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
    return StaticBuildStepResult(
        step_id="article_revisions",
        status="success",
        message=f"Retrieved {len(revisions)} recent edit records.",
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
    return StaticBuildStepResult(
        step_id=step_id,
        status="success",
        message=f"Retrieved {len(items)} daily pageview points.",
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
    return StaticBuildStepResult(
        step_id=step_id,
        status="success",
        message=f"Retrieved {len(results)} {direction} records for {month}.",
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
    return StaticBuildStepResult(
        step_id="editor_summary",
        status="success",
        message=f"Summarized {len(revisions)} edits from {len(editors)} editors.",
    )


async def run_wikidata_entity(target: StaticTargetRecord, client: httpx.AsyncClient) -> StaticBuildStepResult:
    qid = target.article_metadata.wikidata_qid

    if not qid:
        return StaticBuildStepResult(
            step_id="wikidata_entity",
            status="success",
            message="No associated Wikidata entity was declared by the Wikipedia page.",
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
    return StaticBuildStepResult(
        step_id="wikidata_entity",
        status="success",
        message=f"Retrieved Wikidata entity {qid} with {claims} claim groups.",
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
