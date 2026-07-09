from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

import httpx

from wikimedia_search.apis.w_article_metadata import ArticleMetadata, fetch_article_metadata
from wikimedia_search.resolver import ParseError, WIKIMEDIA_USER_AGENT, parse_project_url

TargetEntityType = Literal["w_article"]


@dataclass(frozen=True)
class StaticTargetRecord:
    target_id: str
    type: Literal["static"]
    entity_type: TargetEntityType
    lang: str
    title_slug: str
    canonical_title: str
    canonical_url: str
    article_metadata: ArticleMetadata


_targets_by_identity: dict[str, StaticTargetRecord] = {}
_targets_by_id: dict[str, StaticTargetRecord] = {}


class StaticTargetError(Exception):
    """Raised when a selected search value cannot become a static target."""


class StaticTargetNotFoundError(Exception):
    """Raised when a static target id is not present in the target registry."""


def target_id_for_article(lang: str, page_id: int) -> str:
    digest = hashlib.sha256(f"w_article:{lang}:{page_id}".encode("utf-8")).hexdigest()[:16]
    return f"w_{lang}_{digest}"


async def create_or_get_static_target(selected_url: str) -> StaticTargetRecord:
    parsed = parse_project_url(selected_url)

    if isinstance(parsed, ParseError) or parsed.kind != "wikipedia":
        raise StaticTargetError("Only selected Wikipedia article URLs can create static targets now.")

    async with httpx.AsyncClient(
        headers={"User-Agent": WIKIMEDIA_USER_AGENT},
        timeout=10.0,
    ) as client:
        metadata = await fetch_article_metadata(
            host=parsed.host,
            title=parsed.title,
            client=client,
        )

    identity_key = f"w_article:{metadata.lang}:{metadata.page_id}"
    existing = _targets_by_identity.get(identity_key)
    if existing:
        _targets_by_id[existing.target_id] = existing
        return existing

    target = StaticTargetRecord(
        target_id=target_id_for_article(metadata.lang, metadata.page_id),
        type="static",
        entity_type="w_article",
        lang=metadata.lang,
        title_slug=metadata.title_slug,
        canonical_title=metadata.canonical_title,
        canonical_url=metadata.canonical_url,
        article_metadata=metadata,
    )
    _targets_by_identity[identity_key] = target
    _targets_by_id[target.target_id] = target
    return target


def get_static_target(target_id: str) -> StaticTargetRecord:
    target = _targets_by_id.get(target_id)

    if not target:
        raise StaticTargetNotFoundError("Static target was not found.")

    return target
