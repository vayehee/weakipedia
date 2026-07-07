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
