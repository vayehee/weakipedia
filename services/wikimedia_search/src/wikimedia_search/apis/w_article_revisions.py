from __future__ import annotations

from dataclasses import dataclass

import httpx

from wikimedia_search.apis.http_json import assert_mediawiki_response, get_json


@dataclass(frozen=True)
class ArticleRevisionsPayload:
    raw_json: dict
    revisions: list[dict]


async def fetch_article_revisions(
    *,
    host: str,
    title_slug: str,
    client: httpx.AsyncClient,
    limit: int = 500,
) -> ArticleRevisionsPayload:
    data = await get_json(
        client,
        f"https://{host}/w/api.php",
        params={
            "action": "query",
            "prop": "revisions",
            "titles": title_slug,
            "rvprop": "ids|timestamp|user|userid|comment|size|flags",
            "rvlimit": str(limit),
            "format": "json",
            "formatversion": "2",
            "origin": "*",
        },
    )
    assert_mediawiki_response(data)
    pages = data.get("query", {}).get("pages", [])

    return ArticleRevisionsPayload(
        raw_json=data,
        revisions=pages[0].get("revisions", []) if pages else [],
    )
