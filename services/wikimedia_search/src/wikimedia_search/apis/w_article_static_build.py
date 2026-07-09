from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Awaitable, Callable, Literal

import httpx

from wikimedia_search.apis.w_article_editors import summarize_article_editors
from wikimedia_search.apis.w_article_authorship import fetch_article_authorship
from wikimedia_search.apis.w_article_pageviews import fetch_article_pageviews
from wikimedia_search.apis.w_article_parse import fetch_article_parse
from wikimedia_search.apis.w_article_revisions import fetch_article_revisions
from wikimedia_search.apis.w_article_traffic import fetch_article_traffic
from wikimedia_search.apis.wdata_item import fetch_wikidata_entity
from wikimedia_search.db import (
    DatabaseNotConfiguredError,
    StaticStepCacheResult,
    get_existing_article_authorship,
    get_existing_article_identity,
    get_existing_article_parse,
    get_existing_article_revisions,
    get_existing_article_traffic,
    get_existing_wikidata_entity,
    persist_article_identity,
    persist_article_parse,
    persist_article_authorship,
    persist_article_revisions,
    persist_article_traffic,
    persist_wikidata_entity,
)
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


def earliest_record_at(cache: StaticStepCacheResult) -> str:
    return cache.earliest_record_at.isoformat()


def pageview_dates() -> tuple[str, str]:
    today = date.today()
    start = today - timedelta(days=90)
    return start.strftime("%Y%m%d"), today.strftime("%Y%m%d")


async def run_article_identity(target: StaticTargetRecord, client: httpx.AsyncClient) -> StaticBuildStepResult:
    metadata = target.article_metadata
    existing = await get_existing_article_identity(target)
    if existing:
        return StaticBuildStepResult(
            step_id="article_identity",
            status="success",
            message=(
                f"Reused stored MediaWiki identity for {metadata.canonical_title}: "
                f"target_id={target.target_id}, article_id={target.entity_type}:{target.lang}:{metadata.page_id}, "
                f"page_id={metadata.page_id}, namespace={metadata.namespace}, "
                f"wikidata_qid={metadata.wikidata_qid or 'none'}, "
                f"earliest_record_at={earliest_record_at(existing)}."
            ),
        )

    try:
        persistence = await persist_article_identity(target)
    except DatabaseNotConfiguredError as error:
        raise StaticBuildStepError(str(error)) from error

    return StaticBuildStepResult(
        step_id="article_identity",
        status="success",
        message=(
            f"Stored MediaWiki identity for {metadata.canonical_title}: "
            f"target_id={persistence.target_id}, article_id={persistence.article_id}, "
            f"page_id={metadata.page_id}, namespace={metadata.namespace}, "
            f"wikidata_qid={metadata.wikidata_qid or 'none'}, "
            f"static_build_id={persistence.static_build_id}, "
            f"api_query_id={persistence.api_query_id}."
        ),
    )


async def run_article_parse(target: StaticTargetRecord, client: httpx.AsyncClient) -> StaticBuildStepResult:
    existing = await get_existing_article_parse(target)
    if existing:
        return StaticBuildStepResult(
            step_id="article_parse",
            status="success",
            message=(
                "Reused stored MediaWiki parse payload "
                f"revid={existing.details.get('latest_revid') or 'unknown'}, "
                f"sections={existing.counts['sections_count']}, "
                f"categories={existing.counts['categories_count']}, "
                f"links={existing.counts['links_count']}, "
                f"external_sources={existing.counts['external_sources_count']}, "
                f"templates={existing.counts['templates_count']}, "
                f"earliest_record_at={earliest_record_at(existing)}."
            ),
        )

    parsed = await fetch_article_parse(
        host=target.article_metadata.host,
        title_slug=target.title_slug,
        client=client,
    )

    try:
        persistence = await persist_article_parse(target, parsed)
    except DatabaseNotConfiguredError as error:
        raise StaticBuildStepError(str(error)) from error
    except Exception as error:
        raise StaticBuildStepError(f"Database persistence failed during article parse: {error}.") from error

    return StaticBuildStepResult(
        step_id="article_parse",
        status="success",
        message=(
            "Stored MediaWiki parse payload "
            f"revid={persistence.latest_revid or 'unknown'}, "
            f"sections={persistence.sections_count}, categories={persistence.categories_count}, "
            f"links={persistence.links_count}, external_sources={persistence.external_sources_count}, "
            f"templates={persistence.templates_count}, images={len(parsed.images)}, "
            f"html_bytes={len(parsed.text_html.encode('utf-8'))}, "
            f"api_query_id={persistence.api_query_id}."
        ),
    )


async def run_article_revisions(target: StaticTargetRecord, client: httpx.AsyncClient) -> StaticBuildStepResult:
    existing = await get_existing_article_revisions(target)
    if existing:
        return StaticBuildStepResult(
            step_id="article_revisions",
            status="success",
            message=(
                f"Reused stored {existing.counts['revisions_count']} MediaWiki revision records "
                "with ids, parent ids, timestamps, editor names, comments, byte sizes, and minor flags; "
                f"resolved {existing.counts['editors_count']} editor records from w_editors; "
                f"earliest_record_at={earliest_record_at(existing)}."
            ),
        )

    revisions_payload = await fetch_article_revisions(
        host=target.article_metadata.host,
        title_slug=target.title_slug,
        client=client,
    )

    try:
        persistence = await persist_article_revisions(target, revisions_payload)
    except DatabaseNotConfiguredError as error:
        raise StaticBuildStepError(str(error)) from error
    except Exception as error:
        raise StaticBuildStepError(f"Database persistence failed during article revisions: {error}.") from error

    return StaticBuildStepResult(
        step_id="article_revisions",
        status="success",
        message=(
            f"Stored {persistence.revisions_count} MediaWiki revision records with ids, "
            "parent ids, timestamps, editor names, comments, byte sizes, and minor flags; "
            f"resolved {persistence.editors_count} editor records into w_editors; "
            f"api_query_id={persistence.api_query_id}."
        ),
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
    pageviews = await fetch_article_pageviews(
        lang=target.lang,
        title_slug=target.title_slug,
        access=access,
        agent=agent,
        start=start,
        end=end,
        client=client,
    )
    raise stuck_after_fetch(
        fetched=(
            f"{len(pageviews.items)} pageview points for project={pageviews.project}, access={access}, "
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
    existing = await get_existing_article_traffic(target, direction=direction)
    direction_label = "incoming" if direction == "sources" else "outgoing"
    if existing:
        return StaticBuildStepResult(
            step_id=step_id,
            status="success",
            message=(
                f"Reused stored Wikinav {direction_label} traffic state: "
                f"records={existing.counts['traffic_records_count']}, "
                f"api_queries={existing.counts['api_queries_count']}, "
                f"month={existing.details.get('month') or 'none'}, "
                f"source_status={existing.details.get('source_status') or 'unknown'}, "
                f"http_status={existing.details.get('http_status') or 'unknown'}, "
                f"earliest_record_at={earliest_record_at(existing)}."
            ),
        )

    traffic = await fetch_article_traffic(
        lang=target.lang,
        title_slug=target.title_slug,
        direction=direction,
        client=client,
    )

    try:
        persistence = await persist_article_traffic(target, traffic)
    except DatabaseNotConfiguredError as error:
        raise StaticBuildStepError(str(error)) from error
    except Exception as error:
        raise StaticBuildStepError(f"Database persistence failed during article traffic: {error}.") from error

    if persistence.source_status == "success_no_data":
        return StaticBuildStepResult(
            step_id=step_id,
            status="success",
            message=(
                f"Stored Wikinav {direction_label} traffic no-data state: "
                f"source_status={persistence.source_status}, http_status={persistence.http_status}, "
                f"records=0, api_query_id={persistence.api_query_id}."
            ),
        )

    return StaticBuildStepResult(
        step_id=step_id,
        status="success",
        message=(
            f"Stored {persistence.records_count} Wikinav {direction_label} traffic records "
            f"for month={persistence.month or 'unknown'}, "
            f"total_count={traffic.total_count if traffic.total_count is not None else 'unknown'}, "
            f"api_query_id={persistence.api_query_id}."
        ),
    )


async def run_editor_summary(target: StaticTargetRecord, client: httpx.AsyncClient) -> StaticBuildStepResult:
    revisions_payload = await fetch_article_revisions(
        host=target.article_metadata.host,
        title_slug=target.title_slug,
        client=client,
    )
    editors_payload = summarize_article_editors(revisions_payload)
    raise stuck_after_fetch(
        fetched=(
            f"{editors_payload.revision_count} revision records containing "
            f"{editors_payload.distinct_editor_count} distinct editor names"
        ),
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

    existing = await get_existing_wikidata_entity(target)
    if existing:
        return StaticBuildStepResult(
            step_id="wikidata_entity",
            status="success",
            message=(
                f"Reused stored Wikidata entity {qid}: "
                f"labels={existing.counts['labels_count']}, "
                f"descriptions={existing.counts['descriptions_count']}, "
                f"sitelinks={existing.counts['sitelinks_count']}, "
                f"claim_groups={existing.counts['claim_groups_count']}, "
                f"claims={existing.counts['claims_count']}, "
                f"earliest_record_at={earliest_record_at(existing)}."
            ),
        )

    entity = await fetch_wikidata_entity(qid=qid, client=client)

    try:
        persistence = await persist_wikidata_entity(target, entity)
    except DatabaseNotConfiguredError as error:
        raise StaticBuildStepError(str(error)) from error
    except Exception as error:
        raise StaticBuildStepError(f"Database persistence failed during Wikidata entity processing: {error}.") from error

    return StaticBuildStepResult(
        step_id="wikidata_entity",
        status="success",
        message=(
            f"Stored Wikidata entity {qid}: labels={persistence.labels_count}, "
            f"descriptions={persistence.descriptions_count}, "
            f"sitelinks={persistence.sitelinks_count}, "
            f"claim_groups={persistence.claim_groups_count}, "
            f"claims={persistence.claims_count}, "
            f"api_query_id={persistence.api_query_id}."
        ),
    )


async def run_not_implemented(step_id: str, message: str) -> StaticBuildStepResult:
    raise StaticBuildStepError(message)


StepRunner = Callable[[StaticTargetRecord, httpx.AsyncClient], Awaitable[StaticBuildStepResult]]


async def run_article_authorship(target: StaticTargetRecord, client: httpx.AsyncClient) -> StaticBuildStepResult:
    existing = await get_existing_article_authorship(target)
    if existing:
        return StaticBuildStepResult(
            step_id="article_authorship",
            status="success",
            message=(
                "Reused stored WikiWho current revision text authorship "
                f"revision_id={existing.details.get('revision_id') or 'unknown'}, "
                f"tokens={existing.counts['tokens_count']}, "
                f"editors={existing.counts['editors_count']}, "
                f"earliest_record_at={earliest_record_at(existing)}."
            ),
        )

    authorship = await fetch_article_authorship(
        lang=target.lang,
        page_id=target.article_metadata.page_id,
        client=client,
    )

    try:
        persistence = await persist_article_authorship(target, authorship)
    except DatabaseNotConfiguredError as error:
        raise StaticBuildStepError(str(error)) from error
    except Exception as error:
        raise StaticBuildStepError(f"Database persistence failed during article text authorship: {error}.") from error

    return StaticBuildStepResult(
        step_id="article_authorship",
        status="success",
        message=(
            "Stored WikiWho current revision text authorship "
            f"revision_id={persistence.revision_id or 'unknown'}, "
            f"tokens={persistence.tokens_count}, editors={persistence.editors_count}, "
            f"api_query_id={persistence.api_query_id}."
        ),
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
