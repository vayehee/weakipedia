from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote

import httpx

from wikimedia_search.apis.http_json import get_json

PageviewStreamId = Literal[
    "human",
    "mobile_web",
    "mobile_app",
    "spider",
    "automated",
]

PAGEVIEW_STREAMS: dict[PageviewStreamId, tuple[str, str]] = {
    "human": ("all-access", "user"),
    "mobile_web": ("mobile-web", "user"),
    "mobile_app": ("mobile-app", "user"),
    "spider": ("all-access", "spider"),
    "automated": ("all-access", "automated"),
}


@dataclass(frozen=True)
class ArticlePageviewsPayload:
    raw_json: dict
    project: str
    access: str
    agent: str
    start: str
    end: str
    items: list[dict]
    request_url: str
    stream_id: PageviewStreamId


async def fetch_article_pageviews(
    *,
    lang: str,
    title_slug: str,
    access: str,
    agent: str,
    stream_id: PageviewStreamId,
    start: str,
    end: str,
    client: httpx.AsyncClient,
) -> ArticlePageviewsPayload:
    project = f"{lang}.wikipedia.org"
    url = (
        "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
        f"{project}/{access}/{agent}/{quote(title_slug, safe='')}/daily/{start}/{end}"
    )
    data = await get_json(client, url)

    return ArticlePageviewsPayload(
        raw_json=data,
        project=project,
        access=access,
        agent=agent,
        start=start,
        end=end,
        items=data.get("items", []),
        request_url=url,
        stream_id=stream_id,
    )


async def fetch_article_pageview_streams(
    *,
    lang: str,
    title_slug: str,
    start: str,
    end: str,
    client: httpx.AsyncClient,
) -> list[ArticlePageviewsPayload]:
    payloads: list[ArticlePageviewsPayload] = []
    for stream_id, (access, agent) in PAGEVIEW_STREAMS.items():
        payloads.append(
            await fetch_article_pageviews(
                lang=lang,
                title_slug=title_slug,
                access=access,
                agent=agent,
                stream_id=stream_id,
                start=start,
                end=end,
                client=client,
            )
        )

    return payloads
