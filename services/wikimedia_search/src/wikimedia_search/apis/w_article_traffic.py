from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote

import httpx

from wikimedia_search.apis.http_json import ApiJsonError

TrafficDirection = Literal["sources", "destinations"]

WIKINAV_TITLE_MAP = {
    "other-internal": "Wiki-based traffic",
    "other-search": "Search engine traffic",
    "other-external": "Websites traffic",
    "other-empty": "Anonymous traffic",
    "other-other": "Unidentified traffic",
    "filtered": "Masked-source traffic",
}


@dataclass(frozen=True)
class ArticleTrafficPayload:
    raw_json: dict
    direction: TrafficDirection
    month: str | None
    title: str
    limit: int | None
    total_count: int | None
    results: list[dict]
    request_url: str
    http_status: int
    source_status: Literal["success", "not_found"]
    error_text: str | None = None


def previous_month(month: str) -> str:
    year_text, month_text = month.split("-", 1)
    year = int(year_text)
    month_number = int(month_text)

    if month_number == 1:
        return f"{year - 1}-12"

    return f"{year}-{month_number - 1:02d}"


def chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


async def resolve_namespace_zero_urls(
    *,
    lang: str,
    titles: list[str],
    client: httpx.AsyncClient,
) -> dict[str, str]:
    if not titles:
        return {}

    resolved: dict[str, str] = {}
    for title_chunk in chunks(titles, 50):
        response = await client.get(
            f"https://{lang}.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "redirects": "1",
                "prop": "info",
                "inprop": "url",
                "titles": "|".join(title_chunk),
            },
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ApiJsonError("MediaWiki title resolution response was not a JSON object.")

        normalized_titles = {
            item.get("from"): item.get("to")
            for item in data.get("query", {}).get("normalized", [])
            if item.get("from") and item.get("to")
        }
        redirects = {
            item.get("from"): item.get("to")
            for item in data.get("query", {}).get("redirects", [])
            if item.get("from") and item.get("to")
        }

        for page in data.get("query", {}).get("pages", []):
            if not isinstance(page, dict) or page.get("missing") or page.get("ns") != 0:
                continue

            page_title = page.get("title")
            full_url = page.get("fullurl")
            if not page_title or not full_url:
                continue

            for requested_title in title_chunk:
                normalized = normalized_titles.get(requested_title, requested_title)
                redirected = redirects.get(normalized, normalized)
                if redirected == page_title:
                    resolved[requested_title] = str(full_url)

    return resolved


async def enrich_traffic_results(
    *,
    lang: str,
    results: list[dict],
    client: httpx.AsyncClient,
) -> list[dict]:
    enriched = [dict(result) for result in results]
    titles_to_resolve = [
        str(result.get("title"))
        for result in enriched
        if result.get("title") and str(result.get("title")) not in WIKINAV_TITLE_MAP
    ]
    resolved_urls = await resolve_namespace_zero_urls(
        lang=lang,
        titles=titles_to_resolve,
        client=client,
    )

    for result in enriched:
        title = str(result.get("title") or "")
        if title in WIKINAV_TITLE_MAP:
            result["title_type"] = WIKINAV_TITLE_MAP[title]
            result["url"] = None
            continue

        article_url = resolved_urls.get(title)
        result["title_type"] = article_url
        result["url"] = article_url

    return enriched


async def fetch_article_traffic(
    *,
    lang: str,
    title_slug: str,
    direction: TrafficDirection,
    client: httpx.AsyncClient,
    start: int = 1,
    limit: int = 500,
    sort: str = "desc",
    month: str = "latest",
) -> ArticleTrafficPayload:
    url = (
        f"https://wikinav.wmcloud.org/api/v1/{lang}/"
        f"{quote(title_slug, safe='')}/{direction}/{month}"
    )
    params = {
        "start": str(start),
        "limit": str(limit),
        "sort": sort,
    }
    response = await client.get(url, params=params)

    if response.status_code == 404:
        return ArticleTrafficPayload(
            raw_json={},
            direction=direction,
            month=None,
            title=title_slug,
            limit=limit,
            total_count=0,
            results=[],
            request_url=str(response.request.url),
            http_status=response.status_code,
            source_status="not_found",
            error_text=response.text[:1000],
        )

    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ApiJsonError("Wikinav response was not a JSON object.")
    results = await enrich_traffic_results(
        lang=lang,
        results=data.get("results", []),
        client=client,
    )

    return ArticleTrafficPayload(
        raw_json=data,
        direction=direction,
        month=data.get("month"),
        title=data.get("title", title_slug),
        limit=data.get("limit"),
        total_count=data.get("total_count"),
        results=results,
        request_url=str(response.request.url),
        http_status=response.status_code,
        source_status="success",
    )


async def fetch_article_traffic_available_months(
    *,
    lang: str,
    title_slug: str,
    direction: TrafficDirection,
    client: httpx.AsyncClient,
    limit: int = 500,
) -> list[ArticleTrafficPayload]:
    latest = await fetch_article_traffic(
        lang=lang,
        title_slug=title_slug,
        direction=direction,
        client=client,
        limit=limit,
        month="latest",
    )

    latest_month = latest.month
    if latest.source_status != "success" or not latest_month:
        fallback_direction: TrafficDirection = "sources" if direction == "destinations" else "destinations"
        fallback_latest = await fetch_article_traffic(
            lang=lang,
            title_slug=title_slug,
            direction=fallback_direction,
            client=client,
            limit=limit,
            month="latest",
        )
        latest_month = fallback_latest.month

    if not latest_month:
        return [latest]

    prior_month = previous_month(latest_month)
    prior = await fetch_article_traffic(
        lang=lang,
        title_slug=title_slug,
        direction=direction,
        client=client,
        limit=limit,
        month=prior_month,
    )

    return [latest, prior]
