from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlparse

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

SourceFetchStatus = Literal[
    "success",
    "blocked",
    "no_article_text",
    "archive_requested",
    "archive_not_found",
    "error",
]


@dataclass(frozen=True)
class VisitorBrowserContext:
    user_agent: str | None = None
    language: str | None = None
    languages: tuple[str, ...] = ()
    timezone: str | None = None
    viewport_width: int | None = None
    viewport_height: int | None = None
    device_pixel_ratio: float | None = None
    platform: str | None = None


@dataclass(frozen=True)
class SourceBrowserResult:
    requested_url: str
    final_url: str | None
    http_status: int | None
    content_type: str | None
    title: str | None
    description: str | None
    author: str | None
    publisher: str | None
    publication_name: str | None
    published_at: datetime | None
    language: str | None
    fetched_text: str | None
    fetched_text_status: SourceFetchStatus
    fetched_text_error: str | None
    fetched_text_at: datetime
    extraction_method: str
    raw_metadata: dict[str, Any]
    archive_url: str | None = None


def clean_text(value: str | None) -> str | None:
    if not value:
        return None

    cleaned = " ".join(value.split())
    return cleaned or None


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def preferred_locale(context: VisitorBrowserContext | None) -> str | None:
    if not context:
        return None

    if context.language:
        return context.language

    return context.languages[0] if context.languages else None


def browser_headers(context: VisitorBrowserContext | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if not context:
        return headers

    languages = [language for language in (context.languages or ()) if language]
    if context.language and context.language not in languages:
        languages.insert(0, context.language)

    if languages:
        headers["Accept-Language"] = ", ".join(
            f"{language};q={max(0.1, 1 - index * 0.1):.1f}"
            for index, language in enumerate(languages[:6])
        )

    return headers


def viewport(context: VisitorBrowserContext | None) -> dict[str, int]:
    width = context.viewport_width if context and context.viewport_width else 1366
    height = context.viewport_height if context and context.viewport_height else 768
    return {
        "width": max(320, min(int(width), 2560)),
        "height": max(320, min(int(height), 1600)),
    }


def first_value(metadata: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        value = clean_text(metadata.get(key))
        if value:
            return value
    return None


async def fetch_source_with_browser(
    url: str,
    *,
    visitor_context: VisitorBrowserContext | None = None,
    timeout_ms: int = 20000,
) -> SourceBrowserResult:
    fetched_at = datetime.now(UTC)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        context = await browser.new_context(
            user_agent=visitor_context.user_agent if visitor_context else None,
            locale=preferred_locale(visitor_context),
            timezone_id=visitor_context.timezone if visitor_context else None,
            viewport=viewport(visitor_context),
            device_scale_factor=(
                visitor_context.device_pixel_ratio
                if visitor_context and visitor_context.device_pixel_ratio
                else 1
            ),
            extra_http_headers=browser_headers(visitor_context),
        )

        page = await context.new_page()
        response = None
        try:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            await page.wait_for_load_state("networkidle", timeout=5000)
        except PlaywrightTimeoutError as error:
            await browser.close()
            return SourceBrowserResult(
                requested_url=url,
                final_url=page.url,
                http_status=response.status if response else None,
                content_type=response.headers.get("content-type") if response else None,
                title=None,
                description=None,
                author=None,
                publisher=None,
                publication_name=None,
                published_at=None,
                language=None,
                fetched_text=None,
                fetched_text_status="error",
                fetched_text_error=f"Timed out while loading source page: {error}.",
                fetched_text_at=fetched_at,
                extraction_method="playwright_dom",
                raw_metadata={},
            )

        status = response.status if response else None
        content_type = response.headers.get("content-type") if response else None
        final_url = page.url

        metadata = await page.evaluate(
            """
            () => {
              const values = {};
              for (const element of document.querySelectorAll("meta")) {
                const key = element.getAttribute("property") || element.getAttribute("name");
                const value = element.getAttribute("content");
                if (key && value && !values[key]) values[key] = value;
              }
              return {
                title: document.title || null,
                lang: document.documentElement.lang || null,
                meta: values,
                articleText: Array.from(document.querySelectorAll("article"))
                  .map((element) => element.innerText)
                  .sort((a, b) => b.length - a.length)[0] || null,
                mainText: Array.from(document.querySelectorAll("main"))
                  .map((element) => element.innerText)
                  .sort((a, b) => b.length - a.length)[0] || null,
                bodyText: document.body ? document.body.innerText : null
              };
            }
            """
        )

        await browser.close()

    meta = metadata.get("meta") if isinstance(metadata.get("meta"), dict) else {}
    page_text = clean_text(
        metadata.get("articleText")
        or metadata.get("mainText")
        or metadata.get("bodyText")
    )
    text_status: SourceFetchStatus = "success"
    error: str | None = None

    if status in {401, 402, 403, 451}:
        text_status = "blocked"
        error = f"Source returned HTTP {status}."
        page_text = None
    elif not page_text or len(page_text) < 300:
        text_status = "no_article_text"
        error = "Rendered page did not expose enough readable article text."
        page_text = None

    publication_name = first_value(
        meta,
        "og:site_name",
        "application-name",
        "twitter:site",
    )
    domain = urlparse(url).netloc.lower()
    publisher = first_value(meta, "publisher", "article:publisher") or publication_name or domain

    return SourceBrowserResult(
        requested_url=url,
        final_url=final_url,
        http_status=status,
        content_type=content_type,
        title=clean_text(metadata.get("title")) or first_value(meta, "og:title", "twitter:title"),
        description=first_value(meta, "description", "og:description", "twitter:description"),
        author=first_value(meta, "author", "article:author", "parsely-author"),
        publisher=publisher,
        publication_name=publication_name,
        published_at=parse_datetime(
            first_value(
                meta,
                "article:published_time",
                "datePublished",
                "pubdate",
                "date",
                "publishdate",
            )
        ),
        language=clean_text(metadata.get("lang")) or preferred_locale(visitor_context),
        fetched_text=page_text,
        fetched_text_status=text_status,
        fetched_text_error=error,
        fetched_text_at=fetched_at,
        extraction_method="playwright_dom",
        raw_metadata={
            "meta": meta,
            "visitor_context": {
                "language": visitor_context.language if visitor_context else None,
                "languages": list(visitor_context.languages) if visitor_context else [],
                "timezone": visitor_context.timezone if visitor_context else None,
                "viewport_width": visitor_context.viewport_width if visitor_context else None,
                "viewport_height": visitor_context.viewport_height if visitor_context else None,
                "device_pixel_ratio": visitor_context.device_pixel_ratio if visitor_context else None,
                "platform": visitor_context.platform if visitor_context else None,
            },
        },
    )
