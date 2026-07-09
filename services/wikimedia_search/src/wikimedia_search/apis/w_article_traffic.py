from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote

import httpx

from wikimedia_search.apis.http_json import ApiJsonError

TrafficDirection = Literal["sources", "destinations"]


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


async def fetch_article_traffic(
    *,
    lang: str,
    title_slug: str,
    direction: TrafficDirection,
    client: httpx.AsyncClient,
    start: int = 1,
    limit: int = 500,
    sort: str = "desc",
) -> ArticleTrafficPayload:
    url = (
        f"https://wikinav.wmcloud.org/api/v1/{lang}/"
        f"{quote(title_slug, safe='')}/{direction}/latest"
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

    return ArticleTrafficPayload(
        raw_json=data,
        direction=direction,
        month=data.get("month"),
        title=data.get("title", title_slug),
        limit=data.get("limit"),
        total_count=data.get("total_count"),
        results=data.get("results", []),
        request_url=str(response.request.url),
        http_status=response.status_code,
        source_status="success",
    )
