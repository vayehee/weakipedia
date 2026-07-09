from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlparse

from playwright.async_api import Browser, BrowserContext, Page, Response
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from wikimedia_search.apis.source_browser import (
    SourceBrowserResult,
    SourceFetchStatus,
    VisitorBrowserContext,
    browser_headers,
    clean_text,
    preferred_locale,
    viewport,
)

ARCHIVE_TODAY_HOSTS = {
    "archive.today",
    "archive.is",
    "archive.ph",
    "archive.vn",
    "archive.fo",
    "archive.li",
    "archive.md",
}

DEFAULT_ARCHIVE_HOST = "archive.ph"
MIN_FULL_TEXT_LENGTH = 800
GATED_TEXT_MARKERS = (
    "already a subscriber",
    "become a subscriber",
    "continue reading",
    "create a free account",
    "create an account to continue",
    "log in to continue",
    "register for free to continue",
    "sign in to continue",
    "subscribe for full access",
    "subscribe now to continue",
    "subscribe to continue",
    "subscribe to keep reading",
    "subscription required",
    "this article is for subscribers",
    "to continue reading",
    "unlock this article",
    "you have reached your limit",
)
ARCHIVE_SNAPSHOT_GATED_MARKERS = (
    "please enable js and disable any ad blocker",
    "please enable javascript and disable any ad blocker",
)
TEASER_ARCHIVE_HOSTS = (
    "bloomberg.com",
    "wsj.com",
)


@dataclass(frozen=True)
class ArchiveAttemptResult:
    source_result: SourceBrowserResult
    archive_requested_url: str | None = None
    retry_after: datetime | None = None


def is_archive_today_host(host: str | None) -> bool:
    return bool(host and host.lower() in ARCHIVE_TODAY_HOSTS)


def archive_lookup_url(article_url: str, host: str = DEFAULT_ARCHIVE_HOST) -> str:
    return f"https://{host}/{article_url}"


def archive_save_url(article_url: str, host: str = DEFAULT_ARCHIVE_HOST) -> str:
    return f"https://{host}/?url={quote(article_url, safe='')}"


def is_probable_archive_snapshot_url(url: str) -> bool:
    parsed = urlparse(url)
    if not is_archive_today_host(parsed.netloc):
        return False

    path = parsed.path.strip("/")
    if not path or "/" in path:
        return False

    if path.startswith(("http:", "https:", "www.")) or "*" in path:
        return False

    return path.isalnum() and 3 <= len(path) <= 16


def is_blocked_text(text: str, status: int | None) -> bool:
    lower = text.lower()
    if status in {401, 402, 403, 451}:
        return True

    markers = (
        "i'm not a bot",
        "i am not a bot",
        "not a bot",
        "captcha",
        "bot challenge",
        "access denied",
        "verify you are human",
    )
    return any(marker in lower for marker in markers)


def is_gated_article_text(text: str) -> bool:
    lower = " ".join(text.lower().split())
    return any(marker in lower for marker in GATED_TEXT_MARKERS)


def archive_snapshot_source_host(text: str) -> str | None:
    for line in text.splitlines():
        normalized = " ".join(line.lower().split())
        if normalized.startswith("all snapshots from host "):
            return normalized.removeprefix("all snapshots from host ").strip()

    return None


def is_gated_archive_snapshot_text(text: str) -> bool:
    lower = " ".join(text.lower().split())
    if any(marker in lower for marker in ARCHIVE_SNAPSHOT_GATED_MARKERS):
        return True

    host = archive_snapshot_source_host(text)
    if not host or not any(host.endswith(domain) for domain in TEASER_ARCHIVE_HOSTS):
        return False

    visible_lines = [line.strip() for line in text.splitlines() if line.strip()]
    has_subscribe_chrome = any(line.lower() == "subscribe" for line in visible_lines)
    has_archive_chrome = "archive.today webpage capture" in lower
    return has_archive_chrome and has_subscribe_chrome and len(text) < 3000


def selected_raw_text_status(
    text: str,
    status: int | None,
    *,
    archive_snapshot: bool = False,
) -> SourceFetchStatus:
    if is_blocked_text(text, status):
        return "blocked"

    if is_gated_article_text(text) or (
        archive_snapshot and is_gated_archive_snapshot_text(text)
    ):
        return "no_article_text"

    if len(text) < MIN_FULL_TEXT_LENGTH:
        return "no_article_text"

    return "success"


def text_status_error(
    status: SourceFetchStatus,
    text: str,
    http_status: int | None,
    *,
    archive_snapshot: bool = False,
) -> str | None:
    if status == "success":
        return None

    if status == "blocked":
        return f"Source access blocked; http_status={http_status}."

    if status == "no_article_text" and (
        is_gated_article_text(text)
        or (archive_snapshot and is_gated_archive_snapshot_text(text))
    ):
        return "Source exposed a gated/snippet view rather than full article text."

    if status == "no_article_text" and archive_snapshot:
        return (
            "Archive snapshot did not expose full article text; "
            f"text_length={len(text)}."
        )

    if status == "no_article_text":
        return (
            "Source did not expose enough full text after selecting the page contents; "
            f"text_length={len(text)}."
        )

    return f"Source text extraction ended with status={status}."


async def new_context(browser: Browser, visitor_context: VisitorBrowserContext | None) -> BrowserContext:
    return await browser.new_context(
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


async def select_all_visible_text(page: Page) -> str:
    try:
        await page.keyboard.press("Control+A")
        selected = await page.evaluate("() => window.getSelection().toString()")
        if isinstance(selected, str) and selected.strip():
            return selected
    except Exception:
        pass

    return await page.locator("body").inner_text(timeout=10000)


async def goto_commit(page: Page, url: str, timeout_ms: int) -> Response | None:
    response = await page.goto(url, wait_until="commit", timeout=timeout_ms)
    await page.wait_for_timeout(8000)
    return response


async def read_page(page: Page, url: str, timeout_ms: int) -> tuple[Response | None, str, str]:
    response = await goto_commit(page, url, timeout_ms)
    title = await page.title()
    text = await select_all_visible_text(page)
    return response, title, text


def make_source_result(
    *,
    requested_url: str,
    final_url: str | None,
    response: Response | None,
    title: str | None,
    text: str | None,
    status: SourceFetchStatus,
    error: str | None,
    extraction_method: str,
    raw_metadata: dict[str, Any],
    archive_url: str | None = None,
) -> SourceBrowserResult:
    return SourceBrowserResult(
        requested_url=requested_url,
        final_url=final_url,
        http_status=response.status if response else None,
        content_type=response.headers.get("content-type") if response else None,
        title=clean_text(title),
        description=None,
        author=None,
        publisher=urlparse(final_url or requested_url).netloc.lower() or None,
        publication_name=None,
        published_at=None,
        language=None,
        fetched_text=text if status == "success" else None,
        fetched_text_status=status,
        fetched_text_error=error,
        fetched_text_at=datetime.now(UTC),
        extraction_method=extraction_method,
        raw_metadata=raw_metadata,
        archive_url=archive_url,
    )


async def first_archive_snapshot_url(page: Page, archive_host: str) -> str | None:
    links = await page.evaluate(
        """
        () => Array.from(document.querySelectorAll("a")).map((anchor) => ({
          text: anchor.innerText || "",
          href: anchor.href || ""
        }))
        """
    )
    if not isinstance(links, list):
        return None

    for link in links:
        if not isinstance(link, dict):
            continue

        href = str(link.get("href") or "")
        if is_probable_archive_snapshot_url(href):
            return href

        text = str(link.get("text") or "").strip()
        candidate = f"https://{archive_host}/{text}" if text.isalnum() else ""
        if candidate and is_probable_archive_snapshot_url(candidate):
            return candidate

    return None


def archive_listing_offers_save(text: str) -> bool:
    lower = text.lower()
    return "archive this url" in lower or "save" in lower or "submit" in lower


async def request_archive_save(page: Page, article_url: str, archive_host: str, timeout_ms: int) -> str:
    save_url = archive_save_url(article_url, archive_host)
    await goto_commit(page, save_url, timeout_ms)
    try:
        button = page.locator(
            "button:has-text('save'), input[type=submit], input[value*=save i]"
        ).first
        await button.click(timeout=5000)
        await page.wait_for_timeout(3000)
    except Exception:
        pass

    return save_url


async def fetch_target_source_archive_full_text(
    article_url: str,
    *,
    visitor_context: VisitorBrowserContext | None = None,
    archive_hosts: tuple[str, ...] = tuple(sorted(ARCHIVE_TODAY_HOSTS)),
    timeout_ms: int = 60000,
) -> ArchiveAttemptResult:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        context = await new_context(browser, visitor_context)
        page = await context.new_page()

        try:
            response, title, text = await read_page(page, article_url, timeout_ms)
            direct_is_archive_snapshot = is_probable_archive_snapshot_url(page.url)
            direct_status = selected_raw_text_status(
                text,
                response.status if response else None,
                archive_snapshot=direct_is_archive_snapshot,
            )
            if direct_status == "success":
                await browser.close()
                return ArchiveAttemptResult(
                    source_result=make_source_result(
                        requested_url=article_url,
                        final_url=page.url,
                        response=response,
                        title=title,
                        text=text,
                        status="success",
                        error=None,
                        extraction_method="playwright_select_all_direct",
                        raw_metadata={"access_path": "direct"},
                        archive_url=page.url if direct_is_archive_snapshot else None,
                    )
                )
            direct_error = text_status_error(
                direct_status,
                text,
                response.status if response else None,
                archive_snapshot=direct_is_archive_snapshot,
            )
            if direct_is_archive_snapshot:
                await browser.close()
                return ArchiveAttemptResult(
                    source_result=make_source_result(
                        requested_url=article_url,
                        final_url=page.url,
                        response=response,
                        title=title,
                        text=None,
                        status=direct_status,
                        error=direct_error,
                        extraction_method="archive_today_snapshot_direct_gated",
                        raw_metadata={
                            "access_path": "direct_archive_snapshot",
                            "archive_snapshot_text_length": len(text),
                            "archive_snapshot_host": archive_snapshot_source_host(text),
                        },
                        archive_url=page.url,
                    )
                )
        except PlaywrightTimeoutError:
            direct_status = "error"
            direct_error = "Timed out while loading the direct source URL."
        except Exception:
            direct_status = "error"
            direct_error = "Direct source URL failed before full text could be extracted."

        last_error = direct_error or f"Direct source access ended with status={direct_status}."
        archive_requested_url: str | None = None

        for archive_host in archive_hosts:
            lookup = archive_lookup_url(article_url, archive_host)
            try:
                response, title, listing_text = await read_page(page, lookup, timeout_ms)
                snapshot_url = await first_archive_snapshot_url(page, archive_host)
                if snapshot_url:
                    snapshot_response, snapshot_title, snapshot_text = await read_page(
                        page,
                        snapshot_url,
                        timeout_ms,
                    )
                    snapshot_status = selected_raw_text_status(
                        snapshot_text,
                        snapshot_response.status if snapshot_response else None,
                        archive_snapshot=True,
                    )
                    if snapshot_status == "success":
                        await browser.close()
                        return ArchiveAttemptResult(
                            source_result=make_source_result(
                                requested_url=article_url,
                                final_url=page.url,
                                response=snapshot_response,
                                title=snapshot_title,
                                text=snapshot_text,
                                status="success",
                                error=None,
                                extraction_method="archive_today_snapshot_select_all",
                                raw_metadata={
                                    "access_path": "archive_today_snapshot",
                                    "archive_lookup_url": lookup,
                                    "archive_host": archive_host,
                                },
                                archive_url=snapshot_url,
                            )
                        )

                    if snapshot_status == "no_article_text" and (
                        is_gated_article_text(snapshot_text)
                        or is_gated_archive_snapshot_text(snapshot_text)
                    ):
                        await browser.close()
                        return ArchiveAttemptResult(
                            source_result=make_source_result(
                                requested_url=article_url,
                                final_url=page.url,
                                response=snapshot_response,
                                title=snapshot_title,
                                text=None,
                                status="no_article_text",
                                error=(
                                    "Archive snapshot exposed a gated/snippet view rather "
                                    "than full article text."
                                ),
                                extraction_method="archive_today_snapshot_gated",
                                raw_metadata={
                                    "access_path": "archive_today_snapshot",
                                    "archive_lookup_url": lookup,
                                    "archive_host": archive_host,
                                    "archive_snapshot_text_length": len(snapshot_text),
                                    "archive_snapshot_host": archive_snapshot_source_host(snapshot_text),
                                },
                                archive_url=snapshot_url,
                            )
                        )

                    last_error = (
                        f"Archive snapshot {snapshot_url} did not expose article text; "
                        f"status={snapshot_status}; "
                        f"reason={text_status_error(snapshot_status, snapshot_text, snapshot_response.status if snapshot_response else None, archive_snapshot=True)}"
                    )
                    continue

                if archive_listing_offers_save(listing_text):
                    archive_requested_url = await request_archive_save(
                        page,
                        article_url,
                        archive_host,
                        timeout_ms,
                    )
                    await browser.close()
                    return ArchiveAttemptResult(
                        archive_requested_url=archive_requested_url,
                        retry_after=datetime.now(UTC) + timedelta(minutes=10),
                        source_result=make_source_result(
                            requested_url=article_url,
                            final_url=page.url,
                            response=response,
                            title=title,
                            text=None,
                            status="archive_requested",
                            error=(
                                "No archive.today snapshot was found; requested archiving. "
                                "Retry once after 10 minutes."
                            ),
                            extraction_method="archive_today_request_save",
                            raw_metadata={
                                "access_path": "archive_today_save_request",
                                "archive_lookup_url": lookup,
                                "archive_requested_url": archive_requested_url,
                                "archive_host": archive_host,
                            },
                        ),
                    )

                last_error = f"No archive.today snapshot found at {lookup}."
            except PlaywrightTimeoutError:
                last_error = f"Timed out while checking archive.today host {archive_host}."
            except Exception as error:
                last_error = f"Archive host {archive_host} failed: {error}."

        await browser.close()

    return ArchiveAttemptResult(
        archive_requested_url=archive_requested_url,
        source_result=make_source_result(
            requested_url=article_url,
            final_url=None,
            response=None,
            title=None,
            text=None,
            status="archive_not_found",
            error=last_error,
            extraction_method="archive_today_all_hosts",
            raw_metadata={
                "access_path": "archive_today_all_hosts",
                "archive_hosts": list(archive_hosts),
            },
        ),
    )


async def fetch_and_persist_target_source_archive_full_text(
    article_url: str,
    *,
    visitor_context: VisitorBrowserContext | None = None,
    archive_hosts: tuple[str, ...] = tuple(sorted(ARCHIVE_TODAY_HOSTS)),
    timeout_ms: int = 60000,
) -> ArchiveAttemptResult:
    result = await fetch_target_source_archive_full_text(
        article_url,
        visitor_context=visitor_context,
        archive_hosts=archive_hosts,
        timeout_ms=timeout_ms,
    )

    from wikimedia_search.db import persist_source_browser_result

    await persist_source_browser_result(article_url, result.source_result)
    return result
