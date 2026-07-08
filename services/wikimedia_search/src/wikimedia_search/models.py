from typing import Literal

from pydantic import BaseModel

ProjectKind = Literal["wikipedia", "wikidata"]
ValidationStatus = Literal["idle", "checking", "invalid", "valid"]


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


class StaticTargetCreateRequest(BaseModel):
    selectedUrl: str


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
