from __future__ import annotations

from dataclasses import dataclass

import httpx

from wikimedia_search.apis.http_json import assert_mediawiki_response


@dataclass(frozen=True)
class ArticleRevisionsPayload:
    raw_json: dict
    request_url: str
    revisions: list[dict]


async def fetch_article_revisions(
    *,
    host: str,
    title_slug: str,
    client: httpx.AsyncClient,
    limit: int = 500,
) -> ArticleRevisionsPayload:
    params = {
        "action": "query",
        "prop": "revisions",
        "titles": title_slug,
        "rvprop": "ids|timestamp|user|userid|comment|size|flags",
        "rvlimit": str(limit),
        "format": "json",
        "formatversion": "2",
        "origin": "*",
    }
    response = await client.get(f"https://{host}/w/api.php", params=params)
    response.raise_for_status()
    data = response.json()

    if not isinstance(data, dict):
        raise ValueError("API response was not a JSON object.")

    assert_mediawiki_response(data)
    pages = data.get("query", {}).get("pages", [])

    return ArticleRevisionsPayload(
        raw_json=data,
        request_url=str(response.url),
        revisions=pages[0].get("revisions", []) if pages else [],
    )
