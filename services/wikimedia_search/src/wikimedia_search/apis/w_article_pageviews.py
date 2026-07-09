from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

import httpx

from wikimedia_search.apis.http_json import get_json


@dataclass(frozen=True)
class ArticlePageviewsPayload:
    raw_json: dict
    project: str
    access: str
    agent: str
    start: str
    end: str
    items: list[dict]


async def fetch_article_pageviews(
    *,
    lang: str,
    title_slug: str,
    access: str,
    agent: str,
    start: str,
    end: str,
    client: httpx.AsyncClient,
) -> ArticlePageviewsPayload:
    project = f"{lang}.wikipedia.org"
    data = await get_json(
        client,
        (
            "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
            f"{project}/{access}/{agent}/{quote(title_slug, safe='')}/daily/{start}/{end}"
        ),
    )

    return ArticlePageviewsPayload(
        raw_json=data,
        project=project,
        access=access,
        agent=agent,
        start=start,
        end=end,
        items=data.get("items", []),
    )
