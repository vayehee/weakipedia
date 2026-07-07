from __future__ import annotations

import asyncio
import html
import re
import time
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import quote, unquote, urlparse

import httpx
from rapidfuzz import fuzz

from .models import ResolveResponse, Suggestion

ProjectKind = Literal["wikipedia", "wikidata"]

ERROR_CASE_A = "URL need to point to a Wikipedia or a Wikidata project."
WIKIMEDIA_USER_AGENT = "Weakipedia/0.1 (https://weakipedia.vayehee.com)"
PRIORITY_WIKIPEDIA_HOSTS = [
    "en.wikipedia.org",
    "fr.wikipedia.org",
    "de.wikipedia.org",
    "es.wikipedia.org",
    "it.wikipedia.org",
    "pt.wikipedia.org",
    "nl.wikipedia.org",
    "pl.wikipedia.org",
    "ru.wikipedia.org",
    "uk.wikipedia.org",
    "ar.wikipedia.org",
    "he.wikipedia.org",
    "fa.wikipedia.org",
    "hi.wikipedia.org",
    "ja.wikipedia.org",
    "ko.wikipedia.org",
    "zh.wikipedia.org",
    "id.wikipedia.org",
    "tr.wikipedia.org",
    "vi.wikipedia.org",
]

_wikipedia_hosts_cache: list[str] | None = None
_allusers_cache: dict[tuple[str, str], tuple[float, list[Suggestion]]] = {}
ALLUSERS_CACHE_SECONDS = 300


@dataclass(frozen=True)
class ParsedProjectUrl:
    kind: ProjectKind
    host: str
    title: str


@dataclass(frozen=True)
class ParseError:
    case: Literal["caseA", "caseB"]
    kind: ProjectKind | None = None


def project_name(kind: ProjectKind) -> str:
    return "Wikipedia" if kind == "wikipedia" else "Wikidata"


def validation_message(case: Literal["caseB", "caseC"], kind: ProjectKind) -> str:
    if case == "caseB":
        return f"URL need to point to a {project_name(kind)} asset/article/record/page."

    return f"URL need to point to an existing {project_name(kind)} asset/article/record/page."


def favicon_url(host: str) -> str:
    return f"https://{host}/favicon.ico"


def canonical_wikipedia_url(host: str, title: str) -> str:
    return f"https://{host}/wiki/{quote(title.replace(' ', '_'), safe='_:()')}"


def canonical_wikidata_url(entity_id: str) -> str:
    return f"https://www.wikidata.org/wiki/{entity_id}"


def is_wikipedia_host(host: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9-]+\.wikipedia\.org", host))


def is_wikidata_host(host: str) -> bool:
    return host in {"wikidata.org", "www.wikidata.org"}


def looks_like_url(value: str) -> bool:
    trimmed = value.strip().lower()
    return (
        trimmed.startswith(("http://", "https://"))
        or "wikipedia.org" in trimmed
        or "wikidata.org" in trimmed
    )


def title_from_path(path: str, query: str) -> str:
    if path.startswith("/wiki/"):
        return unquote(path[len("/wiki/") :]).replace("_", " ")

    if path == "/w/index.php":
        params = dict(part.split("=", 1) for part in query.split("&") if "=" in part)
        return unquote(params.get("title", "")).replace("_", " ")

    return ""


def parse_project_url(value: str) -> ParsedProjectUrl | ParseError:
    parsed = urlparse(value.strip())

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ParseError("caseA")

    host = parsed.hostname.lower() if parsed.hostname else ""

    if is_wikipedia_host(host):
        title = title_from_path(parsed.path, parsed.query).strip()
        if not title or title == "Main Page":
            return ParseError("caseB", "wikipedia")
        return ParsedProjectUrl("wikipedia", host, title)

    if is_wikidata_host(host):
        title = title_from_path(parsed.path, parsed.query).strip()
        if not title:
            return ParseError("caseB", "wikidata")
        return ParsedProjectUrl("wikidata", "www.wikidata.org", title)

    return ParseError("caseA")


def normalize_text(value: str) -> str:
    without_accents = "".join(
        character
        for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    )
    return re.sub(r"\s+", " ", without_accents.casefold()).strip()


def clean_snippet(value: str | None) -> str:
    if not value:
        return ""
    return html.unescape(re.sub(r"<[^>]*>", "", value))


def user_name_from_query(query: str) -> str | None:
    match = re.fullmatch(r"\s*User\s*:\s*(.+?)\s*", query, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip()


def user_search_prefixes(user_name: str) -> list[str]:
    cleaned = user_name.strip()
    min_length = min(4, len(cleaned))
    prefixes: list[str] = []
    for length in range(len(cleaned), min_length - 1, -1):
        prefix = cleaned[:length].strip()
        if prefix and prefix not in prefixes:
            prefixes.append(prefix)
    return prefixes


def unique_suggestions(suggestions: list[Suggestion]) -> list[Suggestion]:
    seen: set[str] = set()
    unique: list[Suggestion] = []
    for suggestion in suggestions:
        if suggestion.url in seen:
            continue
        seen.add(suggestion.url)
        unique.append(suggestion)
    return unique


def filter_and_rank_suggestions(suggestions: list[Suggestion], query: str) -> list[Suggestion]:
    normalized_query = normalize_text(query)
    tokens = [token for token in normalized_query.split(" ") if token]

    if not tokens:
        return suggestions

    scored: list[tuple[float, Suggestion]] = []
    for suggestion in suggestions:
        title = normalize_text(suggestion.title)
        haystack = normalize_text(f"{suggestion.title} {suggestion.description}")
        title_contains_all = all(token in title for token in tokens)
        body_contains_all = all(token in haystack for token in tokens)
        fuzzy_score = fuzz.token_set_ratio(normalized_query, title)

        if title_contains_all:
            score = 200 + fuzzy_score
        elif body_contains_all:
            score = 100 + fuzzy_score
        elif fuzzy_score >= 78:
            score = fuzzy_score
        else:
            continue

        scored.append((score, suggestion))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [suggestion for _, suggestion in scored]


def suggestion_title_matches_query(suggestion: Suggestion, query: str) -> bool:
    normalized_query = normalize_text(query)
    normalized_title = normalize_text(suggestion.title)
    normalized_title_without_entity_id = normalize_text(
        re.sub(r"\s+\((?:Q|P|L)\d+\)$", "", suggestion.title, flags=re.IGNORECASE)
    )

    return normalized_query in {normalized_title, normalized_title_without_entity_id}


def rank_user_suggestions(suggestions: list[Suggestion], user_name: str) -> list[Suggestion]:
    normalized_user_name = normalize_text(user_name)
    priority = {host: index for index, host in enumerate(PRIORITY_WIKIPEDIA_HOSTS)}
    scored: list[tuple[float, int, Suggestion]] = []

    for suggestion in suggestions:
        title_user_name = re.sub(r"^User:", "", suggestion.title, flags=re.IGNORECASE)
        normalized_title = normalize_text(title_user_name)
        ratio_score = fuzz.ratio(normalized_user_name, normalized_title)
        prefix_bonus = 5 if normalized_title.startswith(normalized_user_name) else 0
        score = ratio_score + prefix_bonus

        if score < 70:
            continue

        scored.append((score, priority.get(suggestion.source, 999), suggestion))

    scored.sort(key=lambda item: (-item[0], item[1], normalize_text(item[2].title)))
    return [suggestion for _, _, suggestion in scored]


async def wikipedia_hosts(client: httpx.AsyncClient) -> list[str]:
    global _wikipedia_hosts_cache

    if _wikipedia_hosts_cache is not None:
        return _wikipedia_hosts_cache

    try:
        response = await client.get(
            "https://meta.wikimedia.org/w/api.php",
            params={
                "action": "sitematrix",
                "format": "json",
                "origin": "*",
                "smtype": "language",
            },
        )
        response.raise_for_status()
        data = response.json()["sitematrix"]
        hosts: list[str] = []
        for entry in data.values():
            if not isinstance(entry, dict):
                continue
            for site in entry.get("site", []):
                if site.get("code") != "wiki" or "closed" in site:
                    continue
                host = urlparse(site.get("url", "")).hostname or ""
                if is_wikipedia_host(host):
                    hosts.append(host)

        priority = {host: index for index, host in enumerate(PRIORITY_WIKIPEDIA_HOSTS)}
        unique_hosts = sorted(set(hosts), key=lambda host: (priority.get(host, 999), host))
        _wikipedia_hosts_cache = unique_hosts or PRIORITY_WIKIPEDIA_HOSTS
    except Exception:
        _wikipedia_hosts_cache = PRIORITY_WIKIPEDIA_HOSTS

    return _wikipedia_hosts_cache


async def exact_wikipedia_suggestion(
    client: httpx.AsyncClient, parsed: ParsedProjectUrl
) -> Suggestion | None:
    response = await client.get(
        f"https://{parsed.host}/w/api.php",
        params={
            "action": "query",
            "format": "json",
            "origin": "*",
            "prop": "info",
            "redirects": "1",
            "titles": parsed.title,
        },
    )
    response.raise_for_status()
    pages = response.json().get("query", {}).get("pages", {})
    page = next(iter(pages.values()), None)

    if not page or "missing" in page or page.get("ns") not in {0, 2}:
        return None

    return Suggestion(
        description="User page" if page.get("ns") == 2 else "Article",
        faviconUrl=favicon_url(parsed.host),
        source=parsed.host,
        title=page["title"],
        url=canonical_wikipedia_url(parsed.host, page["title"]),
    )


async def exact_wikidata_suggestion(
    client: httpx.AsyncClient, parsed: ParsedProjectUrl
) -> Suggestion | None:
    match = re.fullmatch(r"(Q\d+|P\d+|L\d+)", parsed.title, re.IGNORECASE)
    if not match:
        return None

    entity_id = match.group(1).upper()
    response = await client.get(
        "https://www.wikidata.org/w/api.php",
        params={
            "action": "wbgetentities",
            "format": "json",
            "ids": entity_id,
            "languages": "en",
            "origin": "*",
            "props": "labels|descriptions",
        },
    )
    response.raise_for_status()
    entity = response.json().get("entities", {}).get(entity_id)

    if not entity or "missing" in entity:
        return None

    label = entity.get("labels", {}).get("en", {}).get("value")
    description = entity.get("descriptions", {}).get("en", {}).get("value", entity_id)

    return Suggestion(
        description=description,
        faviconUrl=favicon_url("www.wikidata.org"),
        source="wikidata.org",
        title=f"{label} ({entity_id})" if label else entity_id,
        url=canonical_wikidata_url(entity_id),
    )


async def search_wikipedia_host(
    client: httpx.AsyncClient, host: str, query: str, limit: int = 3
) -> list[Suggestion]:
    response = await client.get(
        f"https://{host}/w/api.php",
        params={
            "action": "opensearch",
            "format": "json",
            "limit": str(limit),
            "namespace": "0",
            "origin": "*",
            "search": query,
        },
    )
    response.raise_for_status()
    _, titles, descriptions, urls = response.json()
    return [
        Suggestion(
            description=descriptions[index] if index < len(descriptions) else "",
            faviconUrl=favicon_url(host),
            source=host,
            title=title,
            url=urls[index] if index < len(urls) and urls[index] else canonical_wikipedia_url(host, title),
        )
        for index, title in enumerate(titles)
    ]


async def search_wikipedia_users_by_prefix(
    client: httpx.AsyncClient, host: str, prefix: str, limit: int = 20
) -> list[Suggestion]:
    cache_key = (host, prefix.casefold())
    cached = _allusers_cache.get(cache_key)
    if cached and time.monotonic() - cached[0] < ALLUSERS_CACHE_SECONDS:
        return cached[1]

    response = await client.get(
        f"https://{host}/w/api.php",
        params={
            "action": "query",
            "format": "json",
            "origin": "*",
            "list": "allusers",
            "auprefix": prefix,
            "auprop": "groups|editcount|registration",
            "aulimit": str(limit),
        },
        )
    response.raise_for_status()
    users = response.json().get("query", {}).get("allusers", [])
    suggestions: list[Suggestion] = []
    for user in users:
        edit_count = user.get("editcount")
        groups = [group for group in user.get("groups", []) if group not in {"*", "user"}]
        details = [f"{edit_count:,} edits"] if isinstance(edit_count, int) else []
        if groups:
            details.append(", ".join(groups[:3]))
        description = "; ".join(details)
        title = f"User:{user['name']}"
        suggestions.append(
            Suggestion(
                description=description,
                faviconUrl=favicon_url(host),
                source=host,
                title=title,
                url=canonical_wikipedia_url(host, title),
            )
        )
    _allusers_cache[cache_key] = (time.monotonic(), suggestions)
    return suggestions


async def search_wikipedia_url_context(
    client: httpx.AsyncClient, parsed: ParsedProjectUrl
) -> list[Suggestion]:
    response = await client.get(
        f"https://{parsed.host}/w/api.php",
        params={
            "action": "query",
            "format": "json",
            "origin": "*",
            "list": "search",
            "srnamespace": "0|2",
            "srlimit": "5",
            "srsearch": parsed.title,
        },
    )
    response.raise_for_status()
    results = response.json().get("query", {}).get("search", [])
    return [
        Suggestion(
            description=clean_snippet(result.get("snippet")),
            faviconUrl=favicon_url(parsed.host),
            source=parsed.host,
            title=result["title"],
            url=canonical_wikipedia_url(parsed.host, result["title"]),
        )
        for result in results
    ]


async def search_wikidata(client: httpx.AsyncClient, query: str, limit: int = 5) -> list[Suggestion]:
    response = await client.get(
        "https://www.wikidata.org/w/api.php",
        params={
            "action": "wbsearchentities",
            "format": "json",
            "language": "en",
            "limit": str(limit),
            "origin": "*",
            "search": query,
        },
    )
    response.raise_for_status()
    results = response.json().get("search", [])
    return [
        Suggestion(
            description=result.get("description") or result["id"],
            faviconUrl=favicon_url("www.wikidata.org"),
            source="wikidata.org",
            title=f"{result.get('label')} ({result['id']})" if result.get("label") else result["id"],
            url=canonical_wikidata_url(result["id"]),
        )
        for result in results
    ]


async def search_all_wikipedia_users(client: httpx.AsyncClient, query: str) -> list[Suggestion]:
    user_name = user_name_from_query(query)
    if not user_name:
        return []

    all_hosts = await wikipedia_hosts(client)
    priority_hosts = [host for host in PRIORITY_WIKIPEDIA_HOSTS if host in all_hosts]
    remaining_hosts = [host for host in all_hosts if host not in set(priority_hosts)]
    host_stages = [priority_hosts, remaining_hosts]
    prefixes = user_search_prefixes(user_name)
    semaphore = asyncio.Semaphore(20)
    suggestions: list[Suggestion] = []

    async def guarded_user_search(host: str, prefix: str) -> list[Suggestion]:
        async with semaphore:
            try:
                return await search_wikipedia_users_by_prefix(client, host, prefix)
            except Exception:
                return []

    for hosts in host_stages:
        if not hosts:
            continue
        for prefix in prefixes:
            prefix_results = await asyncio.gather(
                *(guarded_user_search(host, prefix) for host in hosts)
            )
            suggestions = unique_suggestions(
                suggestions + [item for group in prefix_results for item in group]
            )
            ranked = rank_user_suggestions(suggestions, user_name)
            if len(ranked) >= 10:
                break
        else:
            continue
        break

    return rank_user_suggestions(suggestions, user_name)[:10]


async def search_all_projects(client: httpx.AsyncClient, query: str) -> list[Suggestion]:
    if user_name_from_query(query):
        return await search_all_wikipedia_users(client, query)

    # Warm the full site matrix for the backend, but keep live search responsive on priority hosts.
    asyncio.create_task(wikipedia_hosts(client))
    hosts = PRIORITY_WIKIPEDIA_HOSTS
    semaphore = asyncio.Semaphore(8)

    async def guarded_search(host: str) -> list[Suggestion]:
        async with semaphore:
            try:
                return await search_wikipedia_host(client, host, query)
            except Exception:
                return []

    async def guarded_wikidata_search() -> list[Suggestion]:
        try:
            return await search_wikidata(client, query)
        except Exception:
            return []

    wikipedia_results, wikidata_results = await asyncio.gather(
        asyncio.gather(*(guarded_search(host) for host in hosts)),
        guarded_wikidata_search(),
    )
    suggestions = unique_suggestions(
        [item for group in wikipedia_results for item in group]
        + wikidata_results
    )
    return filter_and_rank_suggestions(suggestions, query)[:10]


async def resolve_input(value: str) -> ResolveResponse:
    trimmed = value.strip()
    if not trimmed:
        return ResolveResponse(canSubmit=False, message="", status="idle", suggestions=[])

    async with httpx.AsyncClient(
        headers={"User-Agent": WIKIMEDIA_USER_AGENT},
        timeout=8.0,
    ) as client:
        if not looks_like_url(trimmed):
            suggestions = await search_all_projects(client, trimmed)
            exact_suggestions = [
                suggestion
                for suggestion in suggestions
                if suggestion_title_matches_query(suggestion, trimmed)
            ]
            if exact_suggestions:
                return ResolveResponse(
                    canSubmit=True,
                    message="",
                    status="valid",
                    suggestions=exact_suggestions,
                )

            return ResolveResponse(
                canSubmit=False,
                message=(
                    "Choose a Wikipedia or Wikidata result."
                    if suggestions
                    else "No Wikipedia or Wikidata results found."
                ),
                status="invalid",
                suggestions=suggestions,
            )

        parsed = parse_project_url(trimmed)
        if isinstance(parsed, ParseError):
            message = ERROR_CASE_A if parsed.case == "caseA" else validation_message("caseB", parsed.kind)
            return ResolveResponse(canSubmit=False, message=message, status="invalid", suggestions=[])

        try:
            exact = (
                await exact_wikipedia_suggestion(client, parsed)
                if parsed.kind == "wikipedia"
                else await exact_wikidata_suggestion(client, parsed)
            )
            if exact:
                return ResolveResponse(
                    canSubmit=True,
                    message="",
                    status="valid",
                    suggestions=[exact],
                )

            suggestions = (
                await search_wikipedia_url_context(client, parsed)
                if parsed.kind == "wikipedia"
                else await search_wikidata(client, parsed.title)
            )
            case_insensitive_matches = [
                suggestion
                for suggestion in suggestions
                if suggestion_title_matches_query(suggestion, parsed.title)
            ]
            if case_insensitive_matches:
                return ResolveResponse(
                    canSubmit=True,
                    message="",
                    status="valid",
                    suggestions=case_insensitive_matches,
                )

            return ResolveResponse(
                canSubmit=False,
                message=validation_message("caseC", parsed.kind),
                status="invalid",
                suggestions=suggestions,
            )
        except Exception:
            return ResolveResponse(
                canSubmit=False,
                message=validation_message("caseC", parsed.kind),
                status="invalid",
                suggestions=[],
            )
