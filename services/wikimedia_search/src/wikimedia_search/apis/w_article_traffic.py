from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote

import httpx

from wikimedia_search.apis.http_json import get_json

TrafficDirection = Literal["sources", "destinations"]


@dataclass(frozen=True)
class ArticleTrafficPayload:
    raw_json: dict
    direction: TrafficDirection
    month: str
    title: str
    limit: int | None
    total_count: int | None
    results: list[dict]


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
    data = await get_json(
        client,
        (
            f"https://wikinav.wmcloud.org/api/v1/{lang}/"
            f"{quote(title_slug, safe='')}/{direction}/latest"
        ),
        params={
            "start": str(start),
            "limit": str(limit),
            "sort": sort,
        },
    )

    return ArticleTrafficPayload(
        raw_json=data,
        direction=direction,
        month=data.get("month", "latest month"),
        title=data.get("title", title_slug),
        limit=data.get("limit"),
        total_count=data.get("total_count"),
        results=data.get("results", []),
    )
