from __future__ import annotations

import json
import os
import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import quote, urlparse
from uuid import uuid4

import asyncpg

from wikimedia_search.apis.w_article_parse import ArticleParsePayload
from wikimedia_search.apis.w_article_revisions import ArticleRevisionsPayload
from wikimedia_search.apis.w_article_authorship import ArticleAuthorshipPayload
from wikimedia_search.apis.source_browser import SourceBrowserResult
from wikimedia_search.apis.g_trends import GoogleTrendsPayload
from wikimedia_search.apis.w_article_pageviews import ArticlePageviewsPayload
from wikimedia_search.apis.w_article_traffic import ArticleTrafficPayload, TrafficDirection
from wikimedia_search.apis.wdata_item import WikidataEntityPayload
from wikimedia_search.static_targets import StaticTargetRecord


class DatabaseNotConfiguredError(Exception):
    """Raised when Cloud SQL/Postgres settings are not available."""


@dataclass(frozen=True)
class ArticleIdentityPersistenceResult:
    target_id: str
    article_id: str
    wikidata_item_id: str | None
    static_build_id: str
    api_query_id: str


@dataclass(frozen=True)
class ArticleParsePersistenceResult:
    article_id: str
    static_build_id: str
    api_query_id: str
    sections_count: int
    links_count: int
    categories_count: int
    templates_count: int
    external_sources_count: int
    latest_revid: int | None


@dataclass(frozen=True)
class ArticleRevisionsPersistenceResult:
    article_id: str
    static_build_id: str
    api_query_id: str
    revisions_count: int
    editors_count: int


@dataclass(frozen=True)
class ArticleAuthorshipPersistenceResult:
    article_id: str
    static_build_id: str
    api_query_id: str
    revision_id: int | None
    tokens_count: int
    editors_count: int


@dataclass(frozen=True)
class WikidataEntityPersistenceResult:
    article_id: str
    wikidata_item_id: str
    static_build_id: str
    api_query_id: str
    labels_count: int
    descriptions_count: int
    sitelinks_count: int
    claim_groups_count: int
    claims_count: int


@dataclass(frozen=True)
class ArticleTrafficPersistenceResult:
    article_id: str
    static_build_id: str
    api_query_ids: tuple[str, ...]
    direction: str
    months: tuple[str, ...]
    records_count: int
    source_status: str
    http_status: int


@dataclass(frozen=True)
class ArticlePageviewsPersistenceResult:
    article_id: str
    static_build_id: str
    api_query_ids: tuple[str, ...]
    start: str
    end: str
    rows_count: int
    points_count: int


@dataclass(frozen=True)
class GoogleTrendsPersistenceResult:
    target_id: str
    static_build_id: str
    api_query_id: str
    rows_count: int
    query: str
    start: str
    end: str


@dataclass(frozen=True)
class StaticStepCacheResult:
    earliest_record_at: datetime
    counts: dict[str, int]
    details: dict[str, str | int | None]


_schema_ready = False


def database_config() -> dict[str, Any]:
    password = os.getenv("DB_PASSWORD")
    name = os.getenv("DB_NAME")
    user = os.getenv("DB_USER")
    host = os.getenv("DB_HOST")
    port = int(os.getenv("DB_PORT", "5432"))

    if not password or not name or not user or not host:
        raise DatabaseNotConfiguredError(
            "Database environment is incomplete. Required: DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD."
        )

    return {
        "host": host,
        "port": port,
        "database": name,
        "user": user,
        "password": password,
    }


async def connect() -> asyncpg.Connection:
    return await asyncpg.connect(**database_config())


async def ensure_schema(conn: asyncpg.Connection) -> None:
    global _schema_ready

    if _schema_ready:
        return

    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS wdata_items (
            id TEXT PRIMARY KEY,
            qid TEXT NOT NULL UNIQUE,
            label TEXT,
            description TEXT,
            canonical_url TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE IF NOT EXISTS w_articles (
            id TEXT PRIMARY KEY,
            lang TEXT NOT NULL,
            page_id BIGINT NOT NULL,
            title_slug TEXT NOT NULL,
            canonical_title TEXT NOT NULL,
            canonical_url TEXT NOT NULL,
            wikidata_item_id TEXT REFERENCES wdata_items(id),
            wikidata_qid TEXT,
            latest_revid BIGINT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(lang, page_id),
            UNIQUE(lang, title_slug)
        );

        CREATE TABLE IF NOT EXISTS targets (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            user_id TEXT,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            route TEXT NOT NULL,
            lang TEXT,
            title_slug TEXT,
            canonical_title TEXT,
            status TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE IF NOT EXISTS static_builds (
            id TEXT PRIMARY KEY,
            target_id TEXT NOT NULL REFERENCES targets(id),
            started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at TIMESTAMPTZ,
            status TEXT NOT NULL,
            error_message TEXT,
            UNIQUE(target_id)
        );

        CREATE TABLE IF NOT EXISTS api_queries (
            id TEXT PRIMARY KEY,
            static_build_id TEXT REFERENCES static_builds(id),
            source_type TEXT NOT NULL,
            request_url TEXT NOT NULL,
            http_status INTEGER,
            response_json JSONB,
            response_hash TEXT,
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            status TEXT NOT NULL,
            error_message TEXT
        );

        CREATE TABLE IF NOT EXISTS w_article_sections (
            id TEXT PRIMARY KEY,
            target_id TEXT NOT NULL REFERENCES targets(id),
            article_id TEXT NOT NULL REFERENCES w_articles(id),
            source_query_id TEXT NOT NULL REFERENCES api_queries(id),
            source_query_kind TEXT NOT NULL,
            section_index TEXT NOT NULL,
            section_title TEXT NOT NULL,
            level INTEGER,
            anchor TEXT,
            text_hash TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(target_id, article_id, section_index)
        );

        CREATE TABLE IF NOT EXISTS w_article_links (
            id TEXT PRIMARY KEY,
            target_id TEXT NOT NULL REFERENCES targets(id),
            article_id TEXT NOT NULL REFERENCES w_articles(id),
            source_query_id TEXT NOT NULL REFERENCES api_queries(id),
            source_query_kind TEXT NOT NULL,
            linked_lang TEXT,
            linked_title TEXT NOT NULL,
            linked_url TEXT,
            section_id TEXT REFERENCES w_article_sections(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE IF NOT EXISTS w_article_categories (
            id TEXT PRIMARY KEY,
            target_id TEXT NOT NULL REFERENCES targets(id),
            article_id TEXT NOT NULL REFERENCES w_articles(id),
            source_query_id TEXT NOT NULL REFERENCES api_queries(id),
            source_query_kind TEXT NOT NULL,
            category_title TEXT NOT NULL,
            sort_key TEXT,
            hidden BOOLEAN,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(target_id, article_id, category_title)
        );

        CREATE TABLE IF NOT EXISTS w_article_templates (
            id TEXT PRIMARY KEY,
            target_id TEXT NOT NULL REFERENCES targets(id),
            article_id TEXT NOT NULL REFERENCES w_articles(id),
            source_query_id TEXT NOT NULL REFERENCES api_queries(id),
            source_query_kind TEXT NOT NULL,
            template_title TEXT NOT NULL,
            template_namespace INTEGER,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(target_id, article_id, template_title)
        );

        CREATE TABLE IF NOT EXISTS target_sources (
            id TEXT PRIMARY KEY,
            canonical_url TEXT NOT NULL,
            original_url TEXT,
            url_hash TEXT,
            domain TEXT,
            registrable_domain TEXT,
            title TEXT,
            description TEXT,
            published_at TIMESTAMPTZ,
            accessed_at TIMESTAMPTZ,
            author TEXT,
            publisher TEXT,
            publication_name TEXT,
            language TEXT,
            archive_url TEXT,
            archive_date DATE,
            doi TEXT,
            isbn TEXT,
            issn TEXT,
            pmid TEXT,
            page TEXT,
            pages TEXT,
            volume TEXT,
            issue TEXT,
            raw_metadata_json JSONB,
            full_text TEXT,
            full_text_added_by_user_id TEXT,
            full_text_added_at TIMESTAMPTZ,
            fetched_text TEXT,
            fetched_text_at TIMESTAMPTZ,
            fetched_text_status TEXT,
            fetched_text_error TEXT,
            final_url TEXT,
            content_type TEXT,
            http_status INTEGER,
            extraction_method TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(canonical_url)
        );

        ALTER TABLE target_sources
            ADD COLUMN IF NOT EXISTS original_url TEXT;

        ALTER TABLE target_sources
            ADD COLUMN IF NOT EXISTS url_hash TEXT;

        ALTER TABLE target_sources
            ADD COLUMN IF NOT EXISTS registrable_domain TEXT;

        ALTER TABLE target_sources
            ADD COLUMN IF NOT EXISTS description TEXT;

        ALTER TABLE target_sources
            ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ;

        ALTER TABLE target_sources
            ADD COLUMN IF NOT EXISTS accessed_at TIMESTAMPTZ;

        ALTER TABLE target_sources
            ADD COLUMN IF NOT EXISTS author TEXT;

        ALTER TABLE target_sources
            ADD COLUMN IF NOT EXISTS publisher TEXT;

        ALTER TABLE target_sources
            ADD COLUMN IF NOT EXISTS publication_name TEXT;

        ALTER TABLE target_sources
            ADD COLUMN IF NOT EXISTS language TEXT;

        ALTER TABLE target_sources
            ADD COLUMN IF NOT EXISTS archive_url TEXT;

        ALTER TABLE target_sources
            ADD COLUMN IF NOT EXISTS archive_date DATE;

        ALTER TABLE target_sources
            ADD COLUMN IF NOT EXISTS doi TEXT;

        ALTER TABLE target_sources
            ADD COLUMN IF NOT EXISTS isbn TEXT;

        ALTER TABLE target_sources
            ADD COLUMN IF NOT EXISTS issn TEXT;

        ALTER TABLE target_sources
            ADD COLUMN IF NOT EXISTS pmid TEXT;

        ALTER TABLE target_sources
            ADD COLUMN IF NOT EXISTS page TEXT;

        ALTER TABLE target_sources
            ADD COLUMN IF NOT EXISTS pages TEXT;

        ALTER TABLE target_sources
            ADD COLUMN IF NOT EXISTS volume TEXT;

        ALTER TABLE target_sources
            ADD COLUMN IF NOT EXISTS issue TEXT;

        ALTER TABLE target_sources
            ADD COLUMN IF NOT EXISTS raw_metadata_json JSONB;

        ALTER TABLE target_sources
            ADD COLUMN IF NOT EXISTS full_text TEXT;

        ALTER TABLE target_sources
            ADD COLUMN IF NOT EXISTS full_text_added_by_user_id TEXT;

        ALTER TABLE target_sources
            ADD COLUMN IF NOT EXISTS full_text_added_at TIMESTAMPTZ;

        ALTER TABLE target_sources
            ADD COLUMN IF NOT EXISTS fetched_text TEXT;

        ALTER TABLE target_sources
            ADD COLUMN IF NOT EXISTS fetched_text_at TIMESTAMPTZ;

        ALTER TABLE target_sources
            ADD COLUMN IF NOT EXISTS fetched_text_status TEXT;

        ALTER TABLE target_sources
            ADD COLUMN IF NOT EXISTS fetched_text_error TEXT;

        ALTER TABLE target_sources
            ADD COLUMN IF NOT EXISTS final_url TEXT;

        ALTER TABLE target_sources
            ADD COLUMN IF NOT EXISTS content_type TEXT;

        ALTER TABLE target_sources
            ADD COLUMN IF NOT EXISTS http_status INTEGER;

        ALTER TABLE target_sources
            ADD COLUMN IF NOT EXISTS extraction_method TEXT;

        ALTER TABLE target_sources
            ALTER COLUMN canonical_url SET NOT NULL;

        ALTER TABLE target_sources
            DROP COLUMN IF EXISTS target_id;

        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'target_sources' AND column_name = 'url'
            ) THEN
                EXECUTE 'UPDATE target_sources SET original_url = COALESCE(original_url, url)';
            END IF;
        END $$;

        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'target_sources' AND column_name = 'source_text'
            ) THEN
                EXECUTE 'UPDATE target_sources SET full_text = COALESCE(full_text, source_text)';
            END IF;
        END $$;

        UPDATE target_sources
        SET url_hash = COALESCE(url_hash, md5(canonical_url))
        WHERE canonical_url IS NOT NULL;

        ALTER TABLE target_sources
            DROP COLUMN IF EXISTS url;

        ALTER TABLE target_sources
            DROP COLUMN IF EXISTS source_text;

        ALTER TABLE target_sources
            DROP COLUMN IF EXISTS source_text_hash;

        ALTER TABLE target_sources
            DROP COLUMN IF EXISTS fetched_at;

        CREATE UNIQUE INDEX IF NOT EXISTS target_sources_canonical_url_idx
            ON target_sources (canonical_url);

        CREATE INDEX IF NOT EXISTS target_sources_domain_idx
            ON target_sources (domain);

        CREATE INDEX IF NOT EXISTS target_sources_published_at_idx
            ON target_sources (published_at);

        CREATE TABLE IF NOT EXISTS w_editors (
            id TEXT PRIMARY KEY,
            lang TEXT NOT NULL,
            editor_name TEXT NOT NULL,
            editor_page_url TEXT,
            edit_count INTEGER,
            groups JSONB,
            registration_date TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(lang, editor_name)
        );

        CREATE TABLE IF NOT EXISTS w_article_revisions (
            id TEXT PRIMARY KEY,
            target_id TEXT NOT NULL REFERENCES targets(id),
            article_id TEXT NOT NULL REFERENCES w_articles(id),
            source_query_id TEXT NOT NULL REFERENCES api_queries(id),
            source_query_kind TEXT NOT NULL,
            revision_id BIGINT NOT NULL,
            parent_revision_id BIGINT,
            editor_id TEXT REFERENCES w_editors(id),
            timestamp TIMESTAMPTZ,
            comment TEXT,
            size_bytes INTEGER,
            minor BOOLEAN,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(article_id, revision_id)
        );

        CREATE TABLE IF NOT EXISTS w_article_text_authorship (
            id TEXT PRIMARY KEY,
            target_id TEXT NOT NULL REFERENCES targets(id),
            article_id TEXT NOT NULL REFERENCES w_articles(id),
            source_query_id TEXT NOT NULL REFERENCES api_queries(id),
            source_query_kind TEXT NOT NULL,
            revision_id BIGINT,
            editor_id TEXT REFERENCES w_editors(id),
            token_text TEXT NOT NULL,
            token_id TEXT,
            token_start INTEGER,
            token_end INTEGER,
            introduced_revision_id BIGINT,
            introduced_at TIMESTAMPTZ,
            section_id TEXT REFERENCES w_article_sections(id),
            in_revision_ids JSONB,
            out_revision_ids JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(article_id, revision_id, token_id)
        );

        CREATE TABLE IF NOT EXISTS w_article_traffic (
            id TEXT PRIMARY KEY,
            target_id TEXT NOT NULL REFERENCES targets(id),
            article_id TEXT NOT NULL REFERENCES w_articles(id),
            source_query_id TEXT NOT NULL REFERENCES api_queries(id),
            source_query_kind TEXT NOT NULL,
            month TEXT,
            direction TEXT NOT NULL,
            title TEXT NOT NULL,
            views INTEGER,
            title_type TEXT,
            url TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(target_id, article_id, month, direction, title)
        );

        CREATE TABLE IF NOT EXISTS w_article_views (
            id TEXT PRIMARY KEY,
            target_id TEXT NOT NULL REFERENCES targets(id),
            article_id TEXT NOT NULL REFERENCES w_articles(id),
            source_query_id TEXT NOT NULL REFERENCES api_queries(id),
            source_query_kind TEXT NOT NULL,
            date DATE NOT NULL,
            desktop_views INTEGER,
            mobile_web_views INTEGER,
            mobile_app_views INTEGER,
            spider_views INTEGER,
            automated_views INTEGER,
            human_views INTEGER,
            machine_access INTEGER,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(target_id, article_id, date)
        );

        ALTER TABLE w_article_views
            ADD COLUMN IF NOT EXISTS human_views INTEGER;

        ALTER TABLE w_article_views
            ADD COLUMN IF NOT EXISTS machine_access INTEGER;

        CREATE TABLE IF NOT EXISTS g_trends (
            id TEXT PRIMARY KEY,
            target_id TEXT NOT NULL REFERENCES targets(id),
            source_query_id TEXT NOT NULL REFERENCES api_queries(id),
            source_query_kind TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            date DATE NOT NULL,
            score INTEGER NOT NULL,
            region TEXT NOT NULL DEFAULT '',
            query TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(target_id, entity_type, entity_id, date, region, query)
        );

        UPDATE g_trends SET region = '' WHERE region IS NULL;

        ALTER TABLE g_trends
            ALTER COLUMN region SET DEFAULT '';

        ALTER TABLE g_trends
            ALTER COLUMN region SET NOT NULL;

        CREATE TABLE IF NOT EXISTS wdata_item_labels (
            id TEXT PRIMARY KEY,
            wdata_item_id TEXT NOT NULL REFERENCES wdata_items(id),
            source_query_id TEXT NOT NULL REFERENCES api_queries(id),
            source_query_kind TEXT NOT NULL,
            language TEXT NOT NULL,
            label TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(wdata_item_id, language)
        );

        CREATE TABLE IF NOT EXISTS wdata_item_descriptions (
            id TEXT PRIMARY KEY,
            wdata_item_id TEXT NOT NULL REFERENCES wdata_items(id),
            source_query_id TEXT NOT NULL REFERENCES api_queries(id),
            source_query_kind TEXT NOT NULL,
            language TEXT NOT NULL,
            description TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(wdata_item_id, language)
        );

        CREATE TABLE IF NOT EXISTS wdata_item_sitelinks (
            id TEXT PRIMARY KEY,
            wdata_item_id TEXT NOT NULL REFERENCES wdata_items(id),
            source_query_id TEXT NOT NULL REFERENCES api_queries(id),
            source_query_kind TEXT NOT NULL,
            site TEXT NOT NULL,
            title TEXT NOT NULL,
            badges JSONB,
            url TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(wdata_item_id, site)
        );

        CREATE TABLE IF NOT EXISTS wdata_item_claims (
            id TEXT PRIMARY KEY,
            wdata_item_id TEXT NOT NULL REFERENCES wdata_items(id),
            source_query_id TEXT NOT NULL REFERENCES api_queries(id),
            source_query_kind TEXT NOT NULL,
            property_id TEXT NOT NULL,
            claim_id TEXT NOT NULL,
            rank TEXT,
            mainsnak_json JSONB,
            qualifiers_json JSONB,
            references_json JSONB,
            claim_json JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(wdata_item_id, claim_id)
        );
        """
    )
    _schema_ready = True


def article_id_for(target: StaticTargetRecord) -> str:
    return f"w_article:{target.lang}:{target.article_metadata.page_id}"


def wikidata_url(qid: str) -> str:
    return f"https://www.wikidata.org/wiki/{qid}"


def wikidata_label(entity: dict, language: str = "en") -> str | None:
    label = entity.get("labels", {}).get(language, {})
    value = label.get("value") if isinstance(label, dict) else None
    return str(value) if value else None


def wikidata_description(entity: dict, language: str = "en") -> str | None:
    description = entity.get("descriptions", {}).get(language, {})
    value = description.get("value") if isinstance(description, dict) else None
    return str(value) if value else None


def public_route_for(target: StaticTargetRecord) -> str:
    title = quote(target.title_slug, safe="_:()")
    return f"/static?target={title}&lang={target.lang}&title={title}&view=overview"


def static_build_id_for(target: StaticTargetRecord) -> str:
    return f"static_build:{target.target_id}"


def stable_row_id(prefix: str, *parts: object) -> str:
    source = ":".join(str(part) for part in parts)
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}:{digest}"


def link_title(link: dict) -> str | None:
    title = link.get("title") or link.get("*")
    return str(title) if title else None


def category_title(category: dict) -> str | None:
    title = category.get("category") or category.get("*")
    return str(title) if title else None


def template_title(template: dict) -> str | None:
    title = template.get("title") or template.get("*")
    return str(title) if title else None


def linked_wikipedia_url(target: StaticTargetRecord, title: str) -> str:
    return f"https://{target.article_metadata.host}/wiki/{quote(title.replace(' ', '_'), safe='_:()')}"


def traffic_direction_value(direction: TrafficDirection) -> str:
    return "in" if direction == "sources" else "out"


def traffic_source_type(direction: TrafficDirection) -> str:
    return "w_article_traffic_incoming" if direction == "sources" else "w_article_traffic_outgoing"


def normalized_external_url(url: str) -> str:
    return url.strip()


def source_url_hash(canonical_url: str) -> str:
    return hashlib.md5(canonical_url.encode("utf-8")).hexdigest()


def editor_id_for(lang: str, editor_name: str, user_id: int | None) -> str:
    if user_id and user_id > 0:
        return f"w_editor:{lang}:{user_id}"

    return stable_row_id("w_editor", lang, editor_name)


def editor_page_url(target: StaticTargetRecord, editor_name: str) -> str:
    return f"https://{target.article_metadata.host}/wiki/User:{quote(editor_name.replace(' ', '_'), safe='_:()')}"


def wikiwho_editor_name(editor_reference: str) -> str:
    if editor_reference.startswith("0|"):
        return editor_reference[2:]

    return f"wikiwho:{editor_reference}"


def wikiwho_editor_page_url(target: StaticTargetRecord, editor_reference: str) -> str | None:
    if editor_reference.startswith("0|"):
        return editor_page_url(target, editor_reference[2:])

    return None


def wikiwho_editor_id(lang: str, editor_reference: str) -> str:
    if editor_reference.isdigit() and int(editor_reference) > 0:
        return f"w_editor:{lang}:{editor_reference}"

    return stable_row_id("w_editor", lang, editor_reference)


def revision_id(revision: dict) -> int | None:
    value = revision.get("revid")
    return int(value) if value is not None else None


def revision_parent_id(revision: dict) -> int | None:
    value = revision.get("parentid")
    return int(value) if value is not None else None


def revision_user_id(revision: dict) -> int | None:
    value = revision.get("userid")
    return int(value) if value is not None else None


def revision_size(revision: dict) -> int | None:
    value = revision.get("size")
    return int(value) if value is not None else None


def revision_timestamp(revision: dict) -> datetime | None:
    value = revision.get("timestamp")
    if not value:
        return None

    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def pageview_item_date(item: dict) -> date | None:
    timestamp = str(item.get("timestamp") or "")
    if len(timestamp) < 8:
        return None

    return date(int(timestamp[:4]), int(timestamp[4:6]), int(timestamp[6:8]))


def pageview_item_views(item: dict) -> int | None:
    value = item.get("views")
    return int(value) if value is not None else None


def pageview_column(stream_id: str) -> str:
    return {
        "humans_desktop": "desktop_views",
        "humans_mobile_web": "mobile_web_views",
        "humans_mobile_app": "mobile_app_views",
        "crawlers": "spider_views",
        "machines": "automated_views",
    }[stream_id]


def summed_pageview_values(values: dict[str, int | None], keys: tuple[str, ...]) -> int:
    return sum(int(values.get(key) or 0) for key in keys)


def cache_result_from_row(
    row: asyncpg.Record | None,
    *,
    count_fields: tuple[str, ...],
    detail_fields: tuple[str, ...] = (),
) -> StaticStepCacheResult | None:
    if not row or not row["earliest_record_at"]:
        return None

    counts = {field: int(row[field] or 0) for field in count_fields}
    if not any(counts.values()):
        return None

    return StaticStepCacheResult(
        earliest_record_at=row["earliest_record_at"],
        counts=counts,
        details={field: row[field] for field in detail_fields},
    )


async def get_existing_article_identity(target: StaticTargetRecord) -> StaticStepCacheResult | None:
    article_id = article_id_for(target)
    qid = target.article_metadata.wikidata_qid
    conn = await connect()
    try:
        await ensure_schema(conn)
        row = await conn.fetchrow(
            """
            SELECT
                (SELECT count(*) FROM targets WHERE id = $1) AS targets_count,
                (SELECT count(*) FROM w_articles WHERE id = $2) AS articles_count,
                (SELECT count(*) FROM wdata_items WHERE id = $3) AS wikidata_items_count,
                (
                    SELECT min(created_at)
                    FROM (
                        SELECT created_at FROM targets WHERE id = $1
                        UNION ALL
                        SELECT created_at FROM w_articles WHERE id = $2
                        UNION ALL
                        SELECT created_at FROM wdata_items WHERE id = $3
                    ) AS existing_records
                ) AS earliest_record_at
            """,
            target.target_id,
            article_id,
            qid,
        )
    finally:
        await conn.close()

    result = cache_result_from_row(
        row,
        count_fields=("targets_count", "articles_count", "wikidata_items_count"),
    )
    if not result:
        return None

    has_identity = result.counts["targets_count"] > 0 and result.counts["articles_count"] > 0
    has_required_wikidata = not qid or result.counts["wikidata_items_count"] > 0
    return result if has_identity and has_required_wikidata else None


async def get_existing_article_parse(target: StaticTargetRecord) -> StaticStepCacheResult | None:
    article_id = article_id_for(target)
    conn = await connect()
    try:
        await ensure_schema(conn)
        row = await conn.fetchrow(
            """
            SELECT
                (SELECT count(*) FROM w_article_sections WHERE target_id = $1 AND article_id = $2) AS sections_count,
                (SELECT count(*) FROM w_article_links WHERE target_id = $1 AND article_id = $2) AS links_count,
                (SELECT count(*) FROM w_article_categories WHERE target_id = $1 AND article_id = $2) AS categories_count,
                (SELECT count(*) FROM w_article_templates WHERE target_id = $1 AND article_id = $2) AS templates_count,
                0 AS external_sources_count,
                (SELECT latest_revid FROM w_articles WHERE id = $2) AS latest_revid,
                (
                    SELECT min(created_at)
                    FROM (
                        SELECT created_at FROM w_article_sections WHERE target_id = $1 AND article_id = $2
                        UNION ALL
                        SELECT created_at FROM w_article_links WHERE target_id = $1 AND article_id = $2
                        UNION ALL
                        SELECT created_at FROM w_article_categories WHERE target_id = $1 AND article_id = $2
                        UNION ALL
                        SELECT created_at FROM w_article_templates WHERE target_id = $1 AND article_id = $2
                    ) AS existing_records
                ) AS earliest_record_at
            """,
            target.target_id,
            article_id,
        )
    finally:
        await conn.close()

    result = cache_result_from_row(
        row,
        count_fields=(
            "sections_count",
            "links_count",
            "categories_count",
            "templates_count",
            "external_sources_count",
        ),
        detail_fields=("latest_revid",),
    )
    if not result:
        return None

    return result if result.counts["sections_count"] > 0 else None


async def get_existing_article_revisions(target: StaticTargetRecord) -> StaticStepCacheResult | None:
    article_id = article_id_for(target)
    conn = await connect()
    try:
        await ensure_schema(conn)
        row = await conn.fetchrow(
            """
            SELECT
                count(*) AS revisions_count,
                count(DISTINCT editor_id) AS editors_count,
                min(created_at) AS earliest_record_at
            FROM w_article_revisions
            WHERE target_id = $1 AND article_id = $2
            """,
            target.target_id,
            article_id,
        )
    finally:
        await conn.close()

    return cache_result_from_row(
        row,
        count_fields=("revisions_count", "editors_count"),
    )


async def get_existing_article_authorship(target: StaticTargetRecord) -> StaticStepCacheResult | None:
    article_id = article_id_for(target)
    conn = await connect()
    try:
        await ensure_schema(conn)
        row = await conn.fetchrow(
            """
            SELECT
                count(*) AS tokens_count,
                count(DISTINCT editor_id) AS editors_count,
                max(revision_id) AS revision_id,
                min(created_at) AS earliest_record_at
            FROM w_article_text_authorship
            WHERE target_id = $1 AND article_id = $2
            """,
            target.target_id,
            article_id,
        )
    finally:
        await conn.close()

    return cache_result_from_row(
        row,
        count_fields=("tokens_count", "editors_count"),
        detail_fields=("revision_id",),
    )


async def get_existing_wikidata_entity(target: StaticTargetRecord) -> StaticStepCacheResult | None:
    qid = target.article_metadata.wikidata_qid
    if not qid:
        return None

    conn = await connect()
    try:
        await ensure_schema(conn)
        row = await conn.fetchrow(
            """
            SELECT
                (SELECT count(*) FROM wdata_items WHERE id = $1) AS items_count,
                (SELECT count(*) FROM wdata_item_labels WHERE wdata_item_id = $1) AS labels_count,
                (SELECT count(*) FROM wdata_item_descriptions WHERE wdata_item_id = $1) AS descriptions_count,
                (SELECT count(*) FROM wdata_item_sitelinks WHERE wdata_item_id = $1) AS sitelinks_count,
                (SELECT count(DISTINCT property_id) FROM wdata_item_claims WHERE wdata_item_id = $1) AS claim_groups_count,
                (SELECT count(*) FROM wdata_item_claims WHERE wdata_item_id = $1) AS claims_count,
                (
                    SELECT min(created_at)
                    FROM (
                        SELECT created_at FROM wdata_items WHERE id = $1
                        UNION ALL
                        SELECT created_at FROM wdata_item_labels WHERE wdata_item_id = $1
                        UNION ALL
                        SELECT created_at FROM wdata_item_descriptions WHERE wdata_item_id = $1
                        UNION ALL
                        SELECT created_at FROM wdata_item_sitelinks WHERE wdata_item_id = $1
                        UNION ALL
                        SELECT created_at FROM wdata_item_claims WHERE wdata_item_id = $1
                    ) AS existing_records
                ) AS earliest_record_at
            """,
            qid,
        )
    finally:
        await conn.close()

    result = cache_result_from_row(
        row,
        count_fields=(
            "items_count",
            "labels_count",
            "descriptions_count",
            "sitelinks_count",
            "claim_groups_count",
            "claims_count",
        ),
    )
    if not result:
        return None

    return result if result.counts["items_count"] > 0 and result.counts["claims_count"] > 0 else None


async def get_existing_article_traffic(
    target: StaticTargetRecord,
    *,
    direction: TrafficDirection,
) -> StaticStepCacheResult | None:
    article_id = article_id_for(target)
    static_build_id = static_build_id_for(target)
    source_type = traffic_source_type(direction)
    direction_value = traffic_direction_value(direction)

    conn = await connect()
    try:
        await ensure_schema(conn)
        row = await conn.fetchrow(
            """
            SELECT
                (SELECT count(*)
                 FROM w_article_traffic
                 WHERE target_id = $1 AND article_id = $2 AND direction = $3) AS traffic_records_count,
                (SELECT count(DISTINCT month)
                 FROM w_article_traffic
                 WHERE target_id = $1 AND article_id = $2 AND direction = $3) AS months_count,
                (SELECT count(*)
                 FROM api_queries
                 WHERE static_build_id = $4 AND source_type = $5 AND status IN ('success', 'success_no_data')) AS api_queries_count,
                (SELECT count(*)
                 FROM api_queries
                 WHERE static_build_id = $4 AND source_type = $5 AND status = 'success_no_data') AS no_data_queries_count,
                (SELECT max(month)
                 FROM w_article_traffic
                 WHERE target_id = $1 AND article_id = $2 AND direction = $3) AS month,
                (SELECT status
                 FROM api_queries
                 WHERE static_build_id = $4 AND source_type = $5 AND status IN ('success', 'success_no_data')
                 ORDER BY fetched_at DESC
                 LIMIT 1) AS source_status,
                (SELECT http_status
                 FROM api_queries
                 WHERE static_build_id = $4 AND source_type = $5 AND status IN ('success', 'success_no_data')
                 ORDER BY fetched_at DESC
                 LIMIT 1) AS http_status,
                (
                    SELECT min(created_at)
                    FROM (
                        SELECT created_at
                        FROM w_article_traffic
                        WHERE target_id = $1 AND article_id = $2 AND direction = $3
                        UNION ALL
                        SELECT fetched_at AS created_at
                        FROM api_queries
                        WHERE static_build_id = $4 AND source_type = $5 AND status IN ('success', 'success_no_data')
                    ) AS existing_records
                ) AS earliest_record_at
            """,
            target.target_id,
            article_id,
            direction_value,
            static_build_id,
            source_type,
        )
    finally:
        await conn.close()

    result = cache_result_from_row(
        row,
        count_fields=(
            "traffic_records_count",
            "months_count",
            "api_queries_count",
            "no_data_queries_count",
        ),
        detail_fields=("month", "source_status", "http_status"),
    )
    if not result:
        return None

    has_complete_no_data_state = result.counts["no_data_queries_count"] >= 2
    has_any_month_capture = result.counts["months_count"] >= 1
    return result if has_complete_no_data_state or has_any_month_capture else None


async def get_existing_article_pageviews(
    target: StaticTargetRecord,
    *,
    start: str,
    end: str,
) -> StaticStepCacheResult | None:
    article_id = article_id_for(target)
    static_build_id = static_build_id_for(target)

    conn = await connect()
    try:
        await ensure_schema(conn)
        row = await conn.fetchrow(
            """
            SELECT
                (SELECT count(*)
                 FROM w_article_views
                 WHERE target_id = $1 AND article_id = $2) AS rows_count,
                (SELECT count(*)
                 FROM api_queries
                 WHERE static_build_id = $3 AND source_type LIKE 'w_article_pageviews_%' AND status = 'success') AS api_queries_count,
                (SELECT min(date)
                 FROM w_article_views
                 WHERE target_id = $1 AND article_id = $2) AS start_date,
                (SELECT max(date)
                 FROM w_article_views
                 WHERE target_id = $1 AND article_id = $2) AS end_date,
                (SELECT min(created_at)
                 FROM w_article_views
                 WHERE target_id = $1 AND article_id = $2) AS earliest_record_at
            """,
            target.target_id,
            article_id,
            static_build_id,
        )
    finally:
        await conn.close()

    result = cache_result_from_row(
        row,
        count_fields=("rows_count", "api_queries_count"),
        detail_fields=("start_date", "end_date"),
    )
    if not result:
        return None

    expected_start = date(int(start[:4]), int(start[4:6]), int(start[6:8]))
    expected_end = date(int(end[:4]), int(end[4:6]), int(end[6:8]))
    start_date = result.details.get("start_date")
    end_date = result.details.get("end_date")
    if start_date and end_date and start_date <= expected_start and end_date >= expected_end:
        return result

    return None


async def get_existing_google_trends(target: StaticTargetRecord) -> StaticStepCacheResult | None:
    conn = await connect()
    try:
        await ensure_schema(conn)
        row = await conn.fetchrow(
            """
            SELECT
                count(*) AS rows_count,
                min(date) AS start_date,
                max(date) AS end_date,
                min(created_at) AS earliest_record_at
            FROM g_trends
            WHERE target_id = $1 AND entity_type = $2 AND entity_id = $3
            """,
            target.target_id,
            target.entity_type,
            str(target.article_metadata.page_id),
        )
    finally:
        await conn.close()

    return cache_result_from_row(
        row,
        count_fields=("rows_count",),
        detail_fields=("start_date", "end_date"),
    )


async def persist_article_identity(
    target: StaticTargetRecord,
) -> ArticleIdentityPersistenceResult:
    metadata = target.article_metadata
    article_id = article_id_for(target)
    wikidata_item_id = metadata.wikidata_qid
    static_build_id = static_build_id_for(target)
    api_query_id = f"api_query:{uuid4()}"
    now = datetime.now(UTC)

    conn = await connect()
    try:
        await ensure_schema(conn)

        async with conn.transaction():
            if metadata.wikidata_qid:
                await conn.execute(
                    """
                    INSERT INTO wdata_items (id, qid, canonical_url, updated_at)
                    VALUES ($1, $1, $2, $3)
                    ON CONFLICT (qid) DO UPDATE SET
                        canonical_url = EXCLUDED.canonical_url,
                        updated_at = EXCLUDED.updated_at
                    """,
                    metadata.wikidata_qid,
                    wikidata_url(metadata.wikidata_qid),
                    now,
                )

            await conn.execute(
                """
                INSERT INTO w_articles (
                    id, lang, page_id, title_slug, canonical_title, canonical_url,
                    wikidata_item_id, wikidata_qid, created_at, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $9)
                ON CONFLICT (lang, page_id) DO UPDATE SET
                    title_slug = EXCLUDED.title_slug,
                    canonical_title = EXCLUDED.canonical_title,
                    canonical_url = EXCLUDED.canonical_url,
                    wikidata_item_id = EXCLUDED.wikidata_item_id,
                    wikidata_qid = EXCLUDED.wikidata_qid,
                    updated_at = EXCLUDED.updated_at
                """,
                article_id,
                target.lang,
                metadata.page_id,
                target.title_slug,
                target.canonical_title,
                target.canonical_url,
                wikidata_item_id,
                metadata.wikidata_qid,
                now,
            )

            await conn.execute(
                """
                INSERT INTO targets (
                    id, type, user_id, entity_type, entity_id, route, lang, title_slug,
                    canonical_title, status, created_at, updated_at
                )
                VALUES ($1, $2, NULL, $3, $4, $5, $6, $7, $8, 'building', $9, $9)
                ON CONFLICT (id) DO UPDATE SET
                    entity_id = EXCLUDED.entity_id,
                    route = EXCLUDED.route,
                    lang = EXCLUDED.lang,
                    title_slug = EXCLUDED.title_slug,
                    canonical_title = EXCLUDED.canonical_title,
                    status = EXCLUDED.status,
                    updated_at = EXCLUDED.updated_at
                """,
                target.target_id,
                target.type,
                target.entity_type,
                article_id,
                public_route_for(target),
                target.lang,
                target.title_slug,
                target.canonical_title,
                now,
            )

            await conn.execute(
                """
                INSERT INTO static_builds (id, target_id, started_at, status)
                VALUES ($1, $2, $3, 'building')
                ON CONFLICT (target_id) DO UPDATE SET
                    status = 'building',
                    error_message = NULL
                """,
                static_build_id,
                target.target_id,
                now,
            )

            await conn.execute(
                """
                INSERT INTO api_queries (
                    id, static_build_id, source_type, request_url, http_status,
                    response_json, fetched_at, status
                )
                VALUES ($1, $2, 'w_article_metadata', $3, 200, $4::jsonb, $5, 'success')
                """,
                api_query_id,
                static_build_id,
                metadata.request_url,
                json.dumps(metadata.raw_json),
                now,
            )
    finally:
        await conn.close()

    return ArticleIdentityPersistenceResult(
        target_id=target.target_id,
        article_id=article_id,
        wikidata_item_id=wikidata_item_id,
        static_build_id=static_build_id,
        api_query_id=api_query_id,
    )


async def persist_article_parse(
    target: StaticTargetRecord,
    parsed: ArticleParsePayload,
) -> ArticleParsePersistenceResult:
    article_id = article_id_for(target)
    static_build_id = static_build_id_for(target)
    api_query_id = f"api_query:{uuid4()}"
    now = datetime.now(UTC)
    source_query_kind = "api_queries"

    conn = await connect()
    try:
        await ensure_schema(conn)

        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO api_queries (
                    id, static_build_id, source_type, request_url, http_status,
                    response_json, fetched_at, status
                )
                VALUES ($1, $2, 'w_article_parse', $3, 200, $4::jsonb, $5, 'success')
                """,
                api_query_id,
                static_build_id,
                parsed.request_url,
                json.dumps(parsed.raw_json),
                now,
            )

            await conn.execute(
                """
                UPDATE w_articles
                SET latest_revid = $1, updated_at = $2
                WHERE id = $3
                """,
                parsed.revid,
                now,
                article_id,
            )

            await conn.execute(
                "DELETE FROM w_article_links WHERE target_id = $1 AND article_id = $2",
                target.target_id,
                article_id,
            )
            await conn.execute(
                "DELETE FROM w_article_sections WHERE target_id = $1 AND article_id = $2",
                target.target_id,
                article_id,
            )
            await conn.execute(
                "DELETE FROM w_article_categories WHERE target_id = $1 AND article_id = $2",
                target.target_id,
                article_id,
            )
            await conn.execute(
                "DELETE FROM w_article_templates WHERE target_id = $1 AND article_id = $2",
                target.target_id,
                article_id,
            )

            for index, section in enumerate(parsed.sections):
                section_index = str(section.get("index") or index)
                section_title = str(section.get("line") or section.get("anchor") or "")
                level = section.get("level")
                await conn.execute(
                    """
                    INSERT INTO w_article_sections (
                        id, target_id, article_id, source_query_id, source_query_kind,
                        section_index, section_title, level, anchor, created_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    ON CONFLICT (target_id, article_id, section_index) DO UPDATE SET
                        source_query_id = EXCLUDED.source_query_id,
                        source_query_kind = EXCLUDED.source_query_kind,
                        section_title = EXCLUDED.section_title,
                        level = EXCLUDED.level,
                        anchor = EXCLUDED.anchor
                    """,
                    f"w_article_section:{target.target_id}:{section_index}",
                    target.target_id,
                    article_id,
                    api_query_id,
                    source_query_kind,
                    section_index,
                    section_title,
                    int(level) if level is not None else None,
                    section.get("anchor"),
                    now,
                )

            link_count = 0
            for index, link in enumerate(parsed.links):
                title = link_title(link)
                if not title:
                    continue

                namespace = int(link.get("ns", 0) or 0)
                linked_url = linked_wikipedia_url(target, title) if namespace == 0 else None
                await conn.execute(
                    """
                    INSERT INTO w_article_links (
                        id, target_id, article_id, source_query_id, source_query_kind,
                        linked_lang, linked_title, linked_url, created_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    """,
                    stable_row_id("w_article_link", target.target_id, api_query_id, index, title),
                    target.target_id,
                    article_id,
                    api_query_id,
                    source_query_kind,
                    target.lang if namespace == 0 else None,
                    title,
                    linked_url,
                    now,
                )
                link_count += 1

            category_count = 0
            for category in parsed.categories:
                title = category_title(category)
                if not title:
                    continue

                await conn.execute(
                    """
                    INSERT INTO w_article_categories (
                        id, target_id, article_id, source_query_id, source_query_kind,
                        category_title, sort_key, hidden, created_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    ON CONFLICT (target_id, article_id, category_title) DO UPDATE SET
                        source_query_id = EXCLUDED.source_query_id,
                        source_query_kind = EXCLUDED.source_query_kind,
                        sort_key = EXCLUDED.sort_key,
                        hidden = EXCLUDED.hidden
                    """,
                    stable_row_id("w_article_category", target.target_id, title),
                    target.target_id,
                    article_id,
                    api_query_id,
                    source_query_kind,
                    title,
                    category.get("sortkey") or category.get("sort"),
                    bool(category.get("hidden")) if "hidden" in category else None,
                    now,
                )
                category_count += 1

            template_count = 0
            for template in parsed.templates:
                title = template_title(template)
                if not title:
                    continue

                await conn.execute(
                    """
                    INSERT INTO w_article_templates (
                        id, target_id, article_id, source_query_id, source_query_kind,
                        template_title, template_namespace, created_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (target_id, article_id, template_title) DO UPDATE SET
                        source_query_id = EXCLUDED.source_query_id,
                        source_query_kind = EXCLUDED.source_query_kind,
                        template_namespace = EXCLUDED.template_namespace
                    """,
                    stable_row_id("w_article_template", target.target_id, title),
                    target.target_id,
                    article_id,
                    api_query_id,
                    source_query_kind,
                    title,
                    int(template["ns"]) if template.get("ns") is not None else None,
                    now,
                )
                template_count += 1

            external_source_count = 0
            for url in parsed.external_links:
                canonical_url = normalized_external_url(url)
                if not canonical_url:
                    continue

                domain = urlparse(canonical_url).netloc.lower() or None
                await conn.execute(
                    """
                    INSERT INTO target_sources (
                        id, canonical_url, original_url, url_hash, domain, registrable_domain,
                        accessed_at, updated_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $5, $6, $6)
                    ON CONFLICT (canonical_url) DO UPDATE SET
                        original_url = COALESCE(target_sources.original_url, EXCLUDED.original_url),
                        url_hash = COALESCE(target_sources.url_hash, EXCLUDED.url_hash),
                        domain = COALESCE(target_sources.domain, EXCLUDED.domain),
                        registrable_domain = COALESCE(target_sources.registrable_domain, EXCLUDED.registrable_domain),
                        accessed_at = COALESCE(target_sources.accessed_at, EXCLUDED.accessed_at),
                        updated_at = EXCLUDED.updated_at
                    """,
                    stable_row_id("target_source", canonical_url),
                    canonical_url,
                    url,
                    source_url_hash(canonical_url),
                    domain,
                    now,
                )
                external_source_count += 1
    finally:
        await conn.close()

    return ArticleParsePersistenceResult(
        article_id=article_id,
        static_build_id=static_build_id,
        api_query_id=api_query_id,
        sections_count=len(parsed.sections),
        links_count=link_count,
        categories_count=category_count,
        templates_count=template_count,
        external_sources_count=external_source_count,
        latest_revid=parsed.revid,
    )


async def persist_source_browser_result(
    canonical_url: str,
    result: SourceBrowserResult,
) -> None:
    conn = await connect()
    try:
        await ensure_schema(conn)
        domain = urlparse(canonical_url).netloc.lower() or None
        await conn.execute(
            """
            INSERT INTO target_sources (
                id, canonical_url, original_url, url_hash, domain, registrable_domain,
                title, description, published_at, accessed_at, author, publisher,
                publication_name, language, raw_metadata_json, fetched_text, fetched_text_at,
                fetched_text_status, fetched_text_error, final_url, content_type, http_status,
                extraction_method, updated_at
            )
            VALUES (
                $1, $2, $3, $4, $5, $5,
                $6, $7, $8, $9, $10, $11,
                $12, $13, $14::jsonb, $15, $16,
                $17, $18, $19, $20, $21,
                $22, $9
            )
            ON CONFLICT (canonical_url) DO UPDATE SET
                original_url = COALESCE(target_sources.original_url, EXCLUDED.original_url),
                url_hash = COALESCE(target_sources.url_hash, EXCLUDED.url_hash),
                domain = COALESCE(target_sources.domain, EXCLUDED.domain),
                registrable_domain = COALESCE(
                    target_sources.registrable_domain,
                    EXCLUDED.registrable_domain
                ),
                title = COALESCE(EXCLUDED.title, target_sources.title),
                description = COALESCE(EXCLUDED.description, target_sources.description),
                published_at = COALESCE(EXCLUDED.published_at, target_sources.published_at),
                accessed_at = EXCLUDED.accessed_at,
                author = COALESCE(EXCLUDED.author, target_sources.author),
                publisher = COALESCE(EXCLUDED.publisher, target_sources.publisher),
                publication_name = COALESCE(
                    EXCLUDED.publication_name,
                    target_sources.publication_name
                ),
                language = COALESCE(EXCLUDED.language, target_sources.language),
                raw_metadata_json = COALESCE(EXCLUDED.raw_metadata_json, target_sources.raw_metadata_json),
                fetched_text = EXCLUDED.fetched_text,
                fetched_text_at = EXCLUDED.fetched_text_at,
                fetched_text_status = EXCLUDED.fetched_text_status,
                fetched_text_error = EXCLUDED.fetched_text_error,
                final_url = EXCLUDED.final_url,
                content_type = EXCLUDED.content_type,
                http_status = EXCLUDED.http_status,
                extraction_method = EXCLUDED.extraction_method,
                updated_at = EXCLUDED.updated_at
            """,
            stable_row_id("target_source", canonical_url),
            canonical_url,
            result.requested_url,
            source_url_hash(canonical_url),
            domain,
            result.title,
            result.description,
            result.published_at,
            result.fetched_text_at,
            result.author,
            result.publisher,
            result.publication_name,
            result.language,
            json.dumps(result.raw_metadata),
            result.fetched_text,
            result.fetched_text_at,
            result.fetched_text_status,
            result.fetched_text_error,
            result.final_url,
            result.content_type,
            result.http_status,
            result.extraction_method,
        )
    finally:
        await conn.close()


async def persist_article_revisions(
    target: StaticTargetRecord,
    revisions_payload: ArticleRevisionsPayload,
) -> ArticleRevisionsPersistenceResult:
    article_id = article_id_for(target)
    static_build_id = static_build_id_for(target)
    api_query_id = f"api_query:{uuid4()}"
    now = datetime.now(UTC)
    source_query_kind = "api_queries"
    editor_ids: set[str] = set()
    stored_revisions = 0

    conn = await connect()
    try:
        await ensure_schema(conn)

        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO api_queries (
                    id, static_build_id, source_type, request_url, http_status,
                    response_json, fetched_at, status
                )
                VALUES ($1, $2, 'w_article_revisions', $3, 200, $4::jsonb, $5, 'success')
                """,
                api_query_id,
                static_build_id,
                revisions_payload.request_url,
                json.dumps(revisions_payload.raw_json),
                now,
            )

            await conn.execute(
                "DELETE FROM w_article_revisions WHERE target_id = $1 AND article_id = $2",
                target.target_id,
                article_id,
            )

            for revision in revisions_payload.revisions:
                rev_id = revision_id(revision)
                editor_name = revision.get("user")

                if rev_id is None:
                    continue

                editor_id = None
                user_id = revision_user_id(revision)

                if editor_name:
                    editor_name = str(editor_name)
                    editor_id = editor_id_for(target.lang, editor_name, user_id)
                    editor_ids.add(editor_id)
                    await conn.execute(
                        """
                        INSERT INTO w_editors (
                            id, lang, editor_name, editor_page_url, created_at, updated_at
                        )
                        VALUES ($1, $2, $3, $4, $5, $5)
                        ON CONFLICT (lang, editor_name) DO UPDATE SET
                            editor_page_url = EXCLUDED.editor_page_url,
                            updated_at = EXCLUDED.updated_at
                        """,
                        editor_id,
                        target.lang,
                        editor_name,
                        editor_page_url(target, editor_name),
                        now,
                    )

                await conn.execute(
                    """
                    INSERT INTO w_article_revisions (
                        id, target_id, article_id, source_query_id, source_query_kind,
                        revision_id, parent_revision_id, editor_id, timestamp, comment,
                        size_bytes, minor, created_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::timestamptz, $10, $11, $12, $13)
                    ON CONFLICT (article_id, revision_id) DO UPDATE SET
                        target_id = EXCLUDED.target_id,
                        source_query_id = EXCLUDED.source_query_id,
                        source_query_kind = EXCLUDED.source_query_kind,
                        parent_revision_id = EXCLUDED.parent_revision_id,
                        editor_id = EXCLUDED.editor_id,
                        timestamp = EXCLUDED.timestamp,
                        comment = EXCLUDED.comment,
                        size_bytes = EXCLUDED.size_bytes,
                        minor = EXCLUDED.minor
                    """,
                    f"w_article_revision:{target.lang}:{rev_id}",
                    target.target_id,
                    article_id,
                    api_query_id,
                    source_query_kind,
                    rev_id,
                    revision_parent_id(revision),
                    editor_id,
                    revision_timestamp(revision),
                    revision.get("comment"),
                    revision_size(revision),
                    bool(revision.get("minor", False)),
                    now,
                )
                stored_revisions += 1
    finally:
        await conn.close()

    return ArticleRevisionsPersistenceResult(
        article_id=article_id,
        static_build_id=static_build_id,
        api_query_id=api_query_id,
        revisions_count=stored_revisions,
        editors_count=len(editor_ids),
    )


def current_revision_tokens(authorship: ArticleAuthorshipPayload) -> tuple[int | None, list[dict]]:
    if not authorship.revisions:
        return None, []

    revision_container = authorship.revisions[0]
    if not isinstance(revision_container, dict) or not revision_container:
        return None, []

    revision_id_text, revision_payload = next(iter(revision_container.items()))
    revision_id_value = int(revision_id_text) if str(revision_id_text).isdigit() else None
    tokens = revision_payload.get("tokens", []) if isinstance(revision_payload, dict) else []
    return revision_id_value, tokens


async def persist_article_authorship(
    target: StaticTargetRecord,
    authorship: ArticleAuthorshipPayload,
) -> ArticleAuthorshipPersistenceResult:
    if not authorship.success:
        raise ValueError(authorship.message or "WikiWho returned success=false.")

    article_id = article_id_for(target)
    static_build_id = static_build_id_for(target)
    api_query_id = f"api_query:{uuid4()}"
    now = datetime.now(UTC)
    source_query_kind = "api_queries"
    revision_id_value, tokens = current_revision_tokens(authorship)
    editor_ids: set[str] = set()
    token_offset = 0
    stored_tokens = 0

    conn = await connect()
    try:
        await ensure_schema(conn)

        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO api_queries (
                    id, static_build_id, source_type, request_url, http_status,
                    response_json, fetched_at, status
                )
                VALUES ($1, $2, 'w_article_authorship', $3, 200, $4::jsonb, $5, 'success')
                """,
                api_query_id,
                static_build_id,
                authorship.request_url,
                json.dumps(authorship.raw_json),
                now,
            )

            await conn.execute(
                "DELETE FROM w_article_text_authorship WHERE target_id = $1 AND article_id = $2",
                target.target_id,
                article_id,
            )

            for index, token in enumerate(tokens):
                if not isinstance(token, dict):
                    continue

                token_text = str(token.get("str") or "")
                token_id = str(token.get("token_id") or index)
                editor_reference = token.get("editor")
                editor_id = None

                if editor_reference is not None:
                    editor_reference = str(editor_reference)
                    editor_id = await upsert_wikiwho_editor(
                        conn,
                        target=target,
                        editor_reference=editor_reference,
                        now=now,
                    )
                    editor_ids.add(editor_id)

                token_start = token_offset
                token_end = token_start + len(token_text)
                token_offset = token_end

                await conn.execute(
                    """
                    INSERT INTO w_article_text_authorship (
                        id, target_id, article_id, source_query_id, source_query_kind,
                        revision_id, editor_id, token_text, token_id, token_start, token_end,
                        introduced_revision_id, in_revision_ids, out_revision_ids, created_at
                    )
                    VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
                        $12, $13::jsonb, $14::jsonb, $15
                    )
                    ON CONFLICT (article_id, revision_id, token_id) DO UPDATE SET
                        target_id = EXCLUDED.target_id,
                        source_query_id = EXCLUDED.source_query_id,
                        source_query_kind = EXCLUDED.source_query_kind,
                        editor_id = EXCLUDED.editor_id,
                        token_text = EXCLUDED.token_text,
                        token_start = EXCLUDED.token_start,
                        token_end = EXCLUDED.token_end,
                        introduced_revision_id = EXCLUDED.introduced_revision_id,
                        in_revision_ids = EXCLUDED.in_revision_ids,
                        out_revision_ids = EXCLUDED.out_revision_ids
                    """,
                    stable_row_id("w_article_text_authorship", target.target_id, revision_id_value, token_id),
                    target.target_id,
                    article_id,
                    api_query_id,
                    source_query_kind,
                    revision_id_value,
                    editor_id,
                    token_text,
                    token_id,
                    token_start,
                    token_end,
                    int(token["o_rev_id"]) if token.get("o_rev_id") is not None else None,
                    json.dumps(token.get("in", [])),
                    json.dumps(token.get("out", [])),
                    now,
                )
                stored_tokens += 1
    finally:
        await conn.close()

    return ArticleAuthorshipPersistenceResult(
        article_id=article_id,
        static_build_id=static_build_id,
        api_query_id=api_query_id,
        revision_id=revision_id_value,
        tokens_count=stored_tokens,
        editors_count=len(editor_ids),
    )


async def persist_article_traffic(
    target: StaticTargetRecord,
    traffic_payloads: list[ArticleTrafficPayload],
) -> ArticleTrafficPersistenceResult:
    if not traffic_payloads:
        raise ValueError("No Wikinav traffic payloads were provided for persistence.")

    article_id = article_id_for(target)
    static_build_id = static_build_id_for(target)
    now = datetime.now(UTC)
    source_query_kind = "api_queries"
    direction_value = traffic_direction_value(traffic_payloads[0].direction)
    source_type = traffic_source_type(traffic_payloads[0].direction)
    api_query_ids: list[str] = []
    months: list[str] = []
    stored_records = 0
    successful_payloads = [payload for payload in traffic_payloads if payload.source_status == "success"]

    conn = await connect()
    try:
        await ensure_schema(conn)

        async with conn.transaction():
            for traffic in traffic_payloads:
                api_query_id = f"api_query:{uuid4()}"
                api_query_ids.append(api_query_id)
                status = "success" if traffic.source_status == "success" else "success_no_data"
                response_json = traffic.raw_json if traffic.raw_json else {
                    "source": "wikinav",
                    "source_status": traffic.source_status,
                    "direction": traffic.direction,
                    "title": traffic.title,
                    "error_text": traffic.error_text,
                }
                error_message = (
                    None
                    if traffic.source_status == "success"
                    else "Wikinav returned HTTP 404; stored as no traffic data available for this direction."
                )

                await conn.execute(
                    """
                    INSERT INTO api_queries (
                        id, static_build_id, source_type, request_url, http_status,
                        response_json, fetched_at, status, error_message
                    )
                    VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9)
                    """,
                    api_query_id,
                    static_build_id,
                    source_type,
                    traffic.request_url,
                    traffic.http_status,
                    json.dumps(response_json),
                    now,
                    status,
                    error_message,
                )

            if successful_payloads:
                await conn.execute(
                    """
                    DELETE FROM w_article_traffic
                    WHERE target_id = $1 AND article_id = $2 AND direction = $3
                    """,
                    target.target_id,
                    article_id,
                    direction_value,
                )

            for index, traffic in enumerate(traffic_payloads):
                if traffic.source_status != "success":
                    continue

                if traffic.month:
                    months.append(traffic.month)

                api_query_id = api_query_ids[index]
                for result in traffic.results:
                    title = str(result.get("title") or "")
                    if not title:
                        continue

                    views = result.get("views")
                    await conn.execute(
                        """
                        INSERT INTO w_article_traffic (
                            id, target_id, article_id, source_query_id, source_query_kind,
                            month, direction, title, views, title_type, url, created_at
                        )
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                        ON CONFLICT (target_id, article_id, month, direction, title) DO UPDATE SET
                            source_query_id = EXCLUDED.source_query_id,
                            source_query_kind = EXCLUDED.source_query_kind,
                            views = EXCLUDED.views,
                            title_type = EXCLUDED.title_type,
                            url = EXCLUDED.url
                        """,
                        stable_row_id(
                            "w_article_traffic",
                            target.target_id,
                            article_id,
                            traffic.month,
                            direction_value,
                            title,
                        ),
                        target.target_id,
                        article_id,
                        api_query_id,
                        source_query_kind,
                        traffic.month,
                        direction_value,
                        title,
                        int(views) if views is not None else None,
                        result.get("title_type"),
                        result.get("url"),
                        now,
                    )
                    stored_records += 1
    finally:
        await conn.close()

    if all(payload.source_status == "success" for payload in traffic_payloads):
        source_status = "success"
    elif any(payload.source_status == "success" for payload in traffic_payloads):
        source_status = "partial_success_no_data"
    else:
        source_status = "success_no_data"

    return ArticleTrafficPersistenceResult(
        article_id=article_id,
        static_build_id=static_build_id,
        api_query_ids=tuple(api_query_ids),
        direction=direction_value,
        months=tuple(months),
        records_count=stored_records,
        source_status=source_status,
        http_status=max(payload.http_status for payload in traffic_payloads),
    )


async def persist_article_pageviews(
    target: StaticTargetRecord,
    pageview_payloads: list[ArticlePageviewsPayload],
) -> ArticlePageviewsPersistenceResult:
    if not pageview_payloads:
        raise ValueError("No Wikimedia pageview payloads were provided for persistence.")

    article_id = article_id_for(target)
    static_build_id = static_build_id_for(target)
    now = datetime.now(UTC)
    source_query_kind = "api_queries"
    api_query_ids: list[str] = []
    values_by_date: dict[str, dict[str, int | None]] = {}
    source_query_by_date: dict[str, str] = {}
    points_count = 0
    start = min(payload.start for payload in pageview_payloads)
    end = max(payload.end for payload in pageview_payloads)

    conn = await connect()
    try:
        await ensure_schema(conn)

        async with conn.transaction():
            await conn.execute(
                "DELETE FROM w_article_views WHERE target_id = $1 AND article_id = $2",
                target.target_id,
                article_id,
            )

            for payload in pageview_payloads:
                api_query_id = f"api_query:{uuid4()}"
                api_query_ids.append(api_query_id)
                await conn.execute(
                    """
                    INSERT INTO api_queries (
                        id, static_build_id, source_type, request_url, http_status,
                        response_json, fetched_at, status
                    )
                    VALUES ($1, $2, $3, $4, 200, $5::jsonb, $6, 'success')
                    """,
                    api_query_id,
                    static_build_id,
                    f"w_article_pageviews_{payload.stream_id}",
                    payload.request_url,
                    json.dumps(payload.raw_json),
                    now,
                )

                column = pageview_column(payload.stream_id)
                for item in payload.items:
                    item_date = pageview_item_date(item)
                    if not item_date:
                        continue

                    values_by_date.setdefault(item_date, {})
                    values_by_date[item_date][column] = pageview_item_views(item)
                    source_query_by_date[item_date] = api_query_id
                    points_count += 1

            for item_date, values in values_by_date.items():
                human_views = summed_pageview_values(
                    values,
                    ("desktop_views", "mobile_web_views", "mobile_app_views"),
                )
                machine_access = summed_pageview_values(
                    values,
                    ("spider_views", "automated_views"),
                )
                await conn.execute(
                    """
                    INSERT INTO w_article_views (
                        id, target_id, article_id, source_query_id, source_query_kind,
                        date, desktop_views, mobile_web_views, mobile_app_views,
                        spider_views, automated_views, human_views, machine_access,
                        created_at, updated_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6::date, $7, $8, $9, $10, $11, $12, $13, $14, $14)
                    ON CONFLICT (target_id, article_id, date) DO UPDATE SET
                        source_query_id = EXCLUDED.source_query_id,
                        source_query_kind = EXCLUDED.source_query_kind,
                        desktop_views = EXCLUDED.desktop_views,
                        mobile_web_views = EXCLUDED.mobile_web_views,
                        mobile_app_views = EXCLUDED.mobile_app_views,
                        spider_views = EXCLUDED.spider_views,
                        automated_views = EXCLUDED.automated_views,
                        human_views = EXCLUDED.human_views,
                        machine_access = EXCLUDED.machine_access,
                        updated_at = EXCLUDED.updated_at
                    """,
                    stable_row_id("w_article_view", target.target_id, article_id, item_date),
                    target.target_id,
                    article_id,
                    source_query_by_date[item_date],
                    source_query_kind,
                    item_date,
                    values.get("desktop_views"),
                    values.get("mobile_web_views"),
                    values.get("mobile_app_views"),
                    values.get("spider_views"),
                    values.get("automated_views"),
                    human_views,
                    machine_access,
                    now,
                )
    finally:
        await conn.close()

    return ArticlePageviewsPersistenceResult(
        article_id=article_id,
        static_build_id=static_build_id,
        api_query_ids=tuple(api_query_ids),
        start=start,
        end=end,
        rows_count=len(values_by_date),
        points_count=points_count,
    )


async def persist_google_trends(
    target: StaticTargetRecord,
    trends: GoogleTrendsPayload,
) -> GoogleTrendsPersistenceResult:
    static_build_id = static_build_id_for(target)
    api_query_id = f"api_query:{uuid4()}"
    now = datetime.now(UTC)
    source_query_kind = "api_queries"
    entity_id = str(target.article_metadata.page_id)

    conn = await connect()
    try:
        await ensure_schema(conn)

        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO api_queries (
                    id, static_build_id, source_type, request_url, http_status,
                    response_json, fetched_at, status
                )
                VALUES ($1, $2, 'g_trends', $3, 200, $4::jsonb, $5, 'success')
                """,
                api_query_id,
                static_build_id,
                trends.stored_request_url,
                json.dumps(trends.raw_json),
                now,
            )

            await conn.execute(
                """
                DELETE FROM g_trends
                WHERE target_id = $1 AND entity_type = $2 AND entity_id = $3 AND query = $4
                """,
                target.target_id,
                target.entity_type,
                entity_id,
                trends.query,
            )

            for point in trends.points:
                await conn.execute(
                    """
                    INSERT INTO g_trends (
                        id, target_id, source_query_id, source_query_kind,
                        entity_type, entity_id, date, score, region, query,
                        created_at, updated_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7::date, $8, '', $9, $10, $10)
                    ON CONFLICT (target_id, entity_type, entity_id, date, region, query) DO UPDATE SET
                        source_query_id = EXCLUDED.source_query_id,
                        source_query_kind = EXCLUDED.source_query_kind,
                        score = EXCLUDED.score,
                        updated_at = EXCLUDED.updated_at
                    """,
                    stable_row_id(
                        "g_trends",
                        target.target_id,
                        target.entity_type,
                        entity_id,
                        point.date.isoformat(),
                        trends.query,
                    ),
                    target.target_id,
                    api_query_id,
                    source_query_kind,
                    target.entity_type,
                    entity_id,
                    point.date,
                    point.value,
                    trends.query,
                    now,
                )
    finally:
        await conn.close()

    return GoogleTrendsPersistenceResult(
        target_id=target.target_id,
        static_build_id=static_build_id,
        api_query_id=api_query_id,
        rows_count=len(trends.points),
        query=trends.query,
        start=trends.start,
        end=trends.end,
    )


async def upsert_wikiwho_editor(
    conn: asyncpg.Connection,
    *,
    target: StaticTargetRecord,
    editor_reference: str,
    now: datetime,
) -> str:
    editor_name = wikiwho_editor_name(editor_reference)
    existing = await conn.fetchrow(
        "SELECT id FROM w_editors WHERE lang = $1 AND editor_name = $2",
        target.lang,
        editor_name,
    )

    if existing:
        editor_id = existing["id"]
        await conn.execute(
            """
            UPDATE w_editors
            SET updated_at = $1
            WHERE id = $2
            """,
            now,
            editor_id,
        )
        return editor_id

    editor_id = wikiwho_editor_id(target.lang, editor_reference)
    await conn.execute(
        """
        INSERT INTO w_editors (
            id, lang, editor_name, editor_page_url, created_at, updated_at
        )
        VALUES ($1, $2, $3, $4, $5, $5)
        ON CONFLICT (id) DO UPDATE SET
            updated_at = EXCLUDED.updated_at
        """,
        editor_id,
        target.lang,
        editor_name,
        wikiwho_editor_page_url(target, editor_reference),
        now,
    )
    return editor_id


async def persist_wikidata_entity(
    target: StaticTargetRecord,
    entity_payload: WikidataEntityPayload,
) -> WikidataEntityPersistenceResult:
    article_id = article_id_for(target)
    wikidata_item_id = entity_payload.qid
    entity = entity_payload.entity
    static_build_id = static_build_id_for(target)
    api_query_id = f"api_query:{uuid4()}"
    now = datetime.now(UTC)
    source_query_kind = "api_queries"
    claims_count = 0

    if not entity or entity.get("missing"):
        raise ValueError(f"Wikidata entity {entity_payload.qid} was missing from the response.")

    conn = await connect()
    try:
        await ensure_schema(conn)

        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO api_queries (
                    id, static_build_id, source_type, request_url, http_status,
                    response_json, fetched_at, status
                )
                VALUES ($1, $2, 'wdata_item', $3, 200, $4::jsonb, $5, 'success')
                """,
                api_query_id,
                static_build_id,
                entity_payload.request_url,
                json.dumps(entity_payload.raw_json),
                now,
            )

            await conn.execute(
                """
                INSERT INTO wdata_items (
                    id, qid, label, description, canonical_url, created_at, updated_at
                )
                VALUES ($1, $1, $2, $3, $4, $5, $5)
                ON CONFLICT (qid) DO UPDATE SET
                    label = EXCLUDED.label,
                    description = EXCLUDED.description,
                    canonical_url = EXCLUDED.canonical_url,
                    updated_at = EXCLUDED.updated_at
                """,
                wikidata_item_id,
                wikidata_label(entity),
                wikidata_description(entity),
                wikidata_url(wikidata_item_id),
                now,
            )

            await conn.execute(
                """
                UPDATE w_articles
                SET wikidata_item_id = $1, wikidata_qid = $1, updated_at = $2
                WHERE id = $3
                """,
                wikidata_item_id,
                now,
                article_id,
            )

            await conn.execute(
                "DELETE FROM wdata_item_claims WHERE wdata_item_id = $1",
                wikidata_item_id,
            )
            await conn.execute(
                "DELETE FROM wdata_item_sitelinks WHERE wdata_item_id = $1",
                wikidata_item_id,
            )
            await conn.execute(
                "DELETE FROM wdata_item_descriptions WHERE wdata_item_id = $1",
                wikidata_item_id,
            )
            await conn.execute(
                "DELETE FROM wdata_item_labels WHERE wdata_item_id = $1",
                wikidata_item_id,
            )

            for language, label in entity.get("labels", {}).items():
                value = label.get("value") if isinstance(label, dict) else None
                if not value:
                    continue

                await conn.execute(
                    """
                    INSERT INTO wdata_item_labels (
                        id, wdata_item_id, source_query_id, source_query_kind,
                        language, label, created_at, updated_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $7)
                    ON CONFLICT (wdata_item_id, language) DO UPDATE SET
                        source_query_id = EXCLUDED.source_query_id,
                        source_query_kind = EXCLUDED.source_query_kind,
                        label = EXCLUDED.label,
                        updated_at = EXCLUDED.updated_at
                    """,
                    stable_row_id("wdata_label", wikidata_item_id, language),
                    wikidata_item_id,
                    api_query_id,
                    source_query_kind,
                    language,
                    str(value),
                    now,
                )

            for language, description in entity.get("descriptions", {}).items():
                value = description.get("value") if isinstance(description, dict) else None
                if not value:
                    continue

                await conn.execute(
                    """
                    INSERT INTO wdata_item_descriptions (
                        id, wdata_item_id, source_query_id, source_query_kind,
                        language, description, created_at, updated_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $7)
                    ON CONFLICT (wdata_item_id, language) DO UPDATE SET
                        source_query_id = EXCLUDED.source_query_id,
                        source_query_kind = EXCLUDED.source_query_kind,
                        description = EXCLUDED.description,
                        updated_at = EXCLUDED.updated_at
                    """,
                    stable_row_id("wdata_description", wikidata_item_id, language),
                    wikidata_item_id,
                    api_query_id,
                    source_query_kind,
                    language,
                    str(value),
                    now,
                )

            for site, sitelink in entity.get("sitelinks", {}).items():
                if not isinstance(sitelink, dict):
                    continue

                title = sitelink.get("title")
                if not title:
                    continue

                await conn.execute(
                    """
                    INSERT INTO wdata_item_sitelinks (
                        id, wdata_item_id, source_query_id, source_query_kind,
                        site, title, badges, url, created_at, updated_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, $9)
                    ON CONFLICT (wdata_item_id, site) DO UPDATE SET
                        source_query_id = EXCLUDED.source_query_id,
                        source_query_kind = EXCLUDED.source_query_kind,
                        title = EXCLUDED.title,
                        badges = EXCLUDED.badges,
                        url = EXCLUDED.url,
                        updated_at = EXCLUDED.updated_at
                    """,
                    stable_row_id("wdata_sitelink", wikidata_item_id, site),
                    wikidata_item_id,
                    api_query_id,
                    source_query_kind,
                    site,
                    str(title),
                    json.dumps(sitelink.get("badges", [])),
                    sitelink.get("url"),
                    now,
                )

            for property_id, property_claims in entity.get("claims", {}).items():
                if not isinstance(property_claims, list):
                    continue

                for index, claim in enumerate(property_claims):
                    if not isinstance(claim, dict):
                        continue

                    claim_id = str(claim.get("id") or f"{property_id}:{index}")
                    await conn.execute(
                        """
                        INSERT INTO wdata_item_claims (
                            id, wdata_item_id, source_query_id, source_query_kind,
                            property_id, claim_id, rank, mainsnak_json, qualifiers_json,
                            references_json, claim_json, created_at, updated_at
                        )
                        VALUES (
                            $1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb,
                            $10::jsonb, $11::jsonb, $12, $12
                        )
                        ON CONFLICT (wdata_item_id, claim_id) DO UPDATE SET
                            source_query_id = EXCLUDED.source_query_id,
                            source_query_kind = EXCLUDED.source_query_kind,
                            property_id = EXCLUDED.property_id,
                            rank = EXCLUDED.rank,
                            mainsnak_json = EXCLUDED.mainsnak_json,
                            qualifiers_json = EXCLUDED.qualifiers_json,
                            references_json = EXCLUDED.references_json,
                            claim_json = EXCLUDED.claim_json,
                            updated_at = EXCLUDED.updated_at
                        """,
                        stable_row_id("wdata_claim", wikidata_item_id, claim_id),
                        wikidata_item_id,
                        api_query_id,
                        source_query_kind,
                        property_id,
                        claim_id,
                        claim.get("rank"),
                        json.dumps(claim.get("mainsnak")),
                        json.dumps(claim.get("qualifiers")),
                        json.dumps(claim.get("references")),
                        json.dumps(claim),
                        now,
                    )
                    claims_count += 1
    finally:
        await conn.close()

    return WikidataEntityPersistenceResult(
        article_id=article_id,
        wikidata_item_id=wikidata_item_id,
        static_build_id=static_build_id,
        api_query_id=api_query_id,
        labels_count=entity_payload.labels_count,
        descriptions_count=entity_payload.descriptions_count,
        sitelinks_count=entity_payload.sitelinks_count,
        claim_groups_count=entity_payload.claim_groups_count,
        claims_count=claims_count,
    )
