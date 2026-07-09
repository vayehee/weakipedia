import os
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .apis.w_article_static_build import StaticBuildStepError, run_static_build_step
from .apis.w_article_metadata import ArticleMetadataError
from .models import (
    ArticleMetadataResponse,
    ResolveResponse,
    StaticBuildStepRunResponse,
    StaticTargetCreateRequest,
    StaticTargetResponse,
)
from .resolver import resolve_input
from .static_targets import (
    StaticTargetError,
    StaticTargetNotFoundError,
    StaticTargetRecord,
    create_or_get_static_target,
    get_static_target,
)

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS",
        "https://weakipedia.vayehee.com,http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]

app = FastAPI(title="Weakipedia Wikimedia Search")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/resolve", response_model=ResolveResponse)
async def resolve(input: str = Query(..., min_length=1, max_length=500)) -> ResolveResponse:
    return await resolve_input(input)


def static_target_response(target: StaticTargetRecord) -> StaticTargetResponse:
    metadata = target.article_metadata
    return StaticTargetResponse(
        targetId=target.target_id,
        type=target.type,
        entityType=target.entity_type,
        lang=target.lang,
        titleSlug=target.title_slug,
        canonicalTitle=target.canonical_title,
        canonicalUrl=target.canonical_url,
        route=(
            f"/static?target={target.target_id}"
            f"&lang={target.lang}"
            f"&title={quote(target.title_slug, safe='_:()')}"
            "&view=stats"
        ),
        articleMetadata=ArticleMetadataResponse(
            lang=metadata.lang,
            host=metadata.host,
            requestedTitle=metadata.requested_title,
            canonicalTitle=metadata.canonical_title,
            titleSlug=metadata.title_slug,
            canonicalUrl=metadata.canonical_url,
            pageId=metadata.page_id,
            namespace=metadata.namespace,
            wikidataQid=metadata.wikidata_qid,
            redirects=list(metadata.redirects),
        ),
    )


@app.post("/static-targets", response_model=StaticTargetResponse)
async def create_static_target(request: StaticTargetCreateRequest) -> StaticTargetResponse:
    try:
        target = await create_or_get_static_target(request.selectedUrl)
    except StaticTargetError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except ArticleMetadataError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    return static_target_response(target)


@app.get("/static-targets/{target_id}", response_model=StaticTargetResponse)
async def read_static_target(target_id: str) -> StaticTargetResponse:
    try:
        target = get_static_target(target_id)
    except StaticTargetNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    return static_target_response(target)


@app.post(
    "/static-targets/{target_id}/build-steps/{step_id}",
    response_model=StaticBuildStepRunResponse,
)
async def run_static_target_build_step(
    target_id: str,
    step_id: str,
) -> StaticBuildStepRunResponse:
    try:
        target = get_static_target(target_id)
        result = await run_static_build_step(target, step_id)
    except StaticTargetNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except StaticBuildStepError as error:
        return StaticBuildStepRunResponse(
            stepId=step_id,
            status="error",
            message=str(error),
        )
    except httpx.HTTPStatusError as error:
        response_text = error.response.text[:300].replace("\n", " ")
        return StaticBuildStepRunResponse(
            stepId=step_id,
            status="error",
            message=(
                f"External API returned HTTP {error.response.status_code}; "
                f"url={error.request.url}; response={response_text or '<empty>'}."
            ),
        )
    except httpx.HTTPError as error:
        return StaticBuildStepRunResponse(
            stepId=step_id,
            status="error",
            message=f"External API request failed: {error}.",
        )
    except ValueError as error:
        return StaticBuildStepRunResponse(
            stepId=step_id,
            status="error",
            message=f"API response could not be parsed: {error}.",
        )

    return StaticBuildStepRunResponse(
        stepId=result.step_id,
        status=result.status,
        message=result.message,
    )
