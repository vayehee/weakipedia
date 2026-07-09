from __future__ import annotations

from dataclasses import dataclass

import httpx

from wikimedia_search.apis.http_json import assert_mediawiki_response


@dataclass(frozen=True)
class ArticleParsePayload:
    raw_json: dict
    request_url: str
    revid: int | None
    display_title: str | None
    text_html: str
    sections: list[dict]
    categories: list[dict]
    links: list[dict]
    external_links: list[str]
    templates: list[dict]
    images: list[str]


async def fetch_article_parse(
    *,
    host: str,
    title_slug: str,
    client: httpx.AsyncClient,
) -> ArticleParsePayload:
    params = {
        "action": "parse",
        "page": title_slug,
        "prop": "text|sections|categories|links|externallinks|templates|images|revid|displaytitle",
        "formatversion": "2",
        "format": "json",
        "origin": "*",
    }
    response = await client.get(f"https://{host}/w/api.php", params=params)
    response.raise_for_status()
    data = response.json()

    if not isinstance(data, dict):
        raise ValueError("API response was not a JSON object.")

    assert_mediawiki_response(data)
    parsed = data.get("parse", {})

    return ArticleParsePayload(
        raw_json=data,
        request_url=str(response.url),
        revid=parsed.get("revid"),
        display_title=parsed.get("displaytitle"),
        text_html=parsed.get("text", ""),
        sections=parsed.get("sections", []),
        categories=parsed.get("categories", []),
        links=parsed.get("links", []),
        external_links=parsed.get("externallinks", []),
        templates=parsed.get("templates", []),
        images=parsed.get("images", []),
    )
