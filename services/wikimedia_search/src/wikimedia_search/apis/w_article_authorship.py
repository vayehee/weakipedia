from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class ArticleAuthorshipPayload:
    raw_json: dict
    request_url: str
    article_title: str
    page_id: int
    success: bool
    message: str | None
    revisions: list[dict]


async def fetch_article_authorship(
    *,
    lang: str,
    page_id: int,
    client: httpx.AsyncClient,
) -> ArticleAuthorshipPayload:
    params = {
        "o_rev_id": "true",
        "editor": "true",
        "token_id": "true",
        "out": "true",
        "in": "true",
    }
    response = await client.get(
        f"https://wikiwho.wmcloud.org/{lang}/api/v1.0.0-beta/latest_rev_content/page_id/{page_id}/",
        params=params,
    )
    response.raise_for_status()
    data = response.json()

    if not isinstance(data, dict):
        raise ValueError("WikiWho response was not a JSON object.")

    return ArticleAuthorshipPayload(
        raw_json=data,
        request_url=str(response.url),
        article_title=str(data.get("article_title") or ""),
        page_id=int(data.get("page_id") or page_id),
        success=bool(data.get("success")),
        message=data.get("message"),
        revisions=data.get("revisions", []),
    )
