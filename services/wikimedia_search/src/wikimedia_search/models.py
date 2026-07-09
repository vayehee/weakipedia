from typing import Literal

from pydantic import BaseModel

ProjectKind = Literal["wikipedia", "wikidata"]
ValidationStatus = Literal["idle", "checking", "invalid", "valid"]
StaticBuildStepStatus = Literal["success", "error"]


class Suggestion(BaseModel):
    description: str
    faviconUrl: str
    source: str
    title: str
    url: str


class ResolveResponse(BaseModel):
    canSubmit: bool
    message: str
    status: ValidationStatus
    suggestions: list[Suggestion]


class VisitorContextRequest(BaseModel):
    userAgent: str | None = None
    language: str | None = None
    languages: list[str] = []
    timezone: str | None = None
    viewportWidth: int | None = None
    viewportHeight: int | None = None
    screenWidth: int | None = None
    screenHeight: int | None = None
    devicePixelRatio: float | None = None
    platform: str | None = None


class StaticBuildStepRunRequest(BaseModel):
    visitorContext: VisitorContextRequest | None = None


class StaticTargetCreateRequest(BaseModel):
    selectedUrl: str
    visitorContext: VisitorContextRequest | None = None


class ArticleMetadataResponse(BaseModel):
    lang: str
    host: str
    requestedTitle: str
    canonicalTitle: str
    titleSlug: str
    canonicalUrl: str
    pageId: int
    namespace: int
    wikidataQid: str | None
    redirects: list[str]


class StaticTargetResponse(BaseModel):
    targetId: str
    type: str
    entityType: str
    lang: str
    titleSlug: str
    canonicalTitle: str
    canonicalUrl: str
    route: str
    articleMetadata: ArticleMetadataResponse


class StaticBuildStepRunResponse(BaseModel):
    stepId: str
    status: StaticBuildStepStatus
    message: str
