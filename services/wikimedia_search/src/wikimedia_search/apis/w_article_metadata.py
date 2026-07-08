from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

import httpx

from wikimedia_search.resolver import WIKIMEDIA_USER_AGENT


@dataclass(frozen=True)
class ArticleMetadata:
    lang: str
    host: str
    requested_title: str
    canonical_title: str
    title_slug: str
    canonical_url: str
    page_id: int
    namespace: int
    wikidata_qid: str | None
    redirects: tuple[str, ...]


class ArticleMetadataError(Exception):
    """Raised when a Wikipedia article cannot be resolved to namespace 0 metadata."""


def title_slug(title: str) -> str:
    return title.replace(" ", "_")


def canonical_wikipedia_url(host: str, title: str) -> str:
    return f"https://{host}/wiki/{quote(title_slug(title), safe='_:()')}"


def language_from_host(host: str) -> str:
    return host.split(".", 1)[0]


async def fetch_article_metadata(
    *,
    host: str,
    title: str,
    client: httpx.AsyncClient | None = None,
) -> ArticleMetadata:
    close_client = client is None
    http_client = client or httpx.AsyncClient(
        headers={"User-Agent": WIKIMEDIA_USER_AGENT},
        timeout=10.0,
    )

    try:
        response = await http_client.get(
            f"https://{host}/w/api.php",
            params={
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "origin": "*",
                "prop": "info|pageprops",
                "inprop": "url",
                "redirects": "1",
                "titles": title,
            },
        )
        response.raise_for_status()
        data = response.json().get("query", {})
        pages = data.get("pages", [])

        if not pages:
            raise ArticleMetadataError("Wikipedia article metadata response did not include pages.")

        page = pages[0]
        if page.get("missing"):
            raise ArticleMetadataError("Wikipedia article does not exist.")

        namespace = int(page.get("ns", -1))
        if namespace != 0:
            raise ArticleMetadataError("Wikipedia page is not an article namespace page.")

        canonical_title = page["title"]
        redirects = tuple(redirect["from"] for redirect in data.get("redirects", []) if "from" in redirect)
        wikidata_qid = page.get("pageprops", {}).get("wikibase_item")
        page_id = int(page["pageid"])

        return ArticleMetadata(
            lang=language_from_host(host),
            host=host,
            requested_title=title,
            canonical_title=canonical_title,
            title_slug=title_slug(canonical_title),
            canonical_url=page.get("fullurl") or canonical_wikipedia_url(host, canonical_title),
            page_id=page_id,
            namespace=namespace,
            wikidata_qid=wikidata_qid,
            redirects=redirects,
        )
    finally:
        if close_client:
            await http_client.aclose()
