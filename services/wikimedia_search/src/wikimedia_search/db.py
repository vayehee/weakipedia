from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import asyncpg

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
        """
    )
    _schema_ready = True


def article_id_for(target: StaticTargetRecord) -> str:
    return f"w_article:{target.lang}:{target.article_metadata.page_id}"


def wikidata_url(qid: str) -> str:
    return f"https://www.wikidata.org/wiki/{qid}"


def public_route_for(target: StaticTargetRecord) -> str:
    title = quote(target.title_slug, safe="_:()")
    return f"/static?target={title}&lang={target.lang}&title={title}&view=stats"


async def persist_article_identity(
    target: StaticTargetRecord,
) -> ArticleIdentityPersistenceResult:
    metadata = target.article_metadata
    article_id = article_id_for(target)
    wikidata_item_id = metadata.wikidata_qid
    static_build_id = f"static_build:{target.target_id}"
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
