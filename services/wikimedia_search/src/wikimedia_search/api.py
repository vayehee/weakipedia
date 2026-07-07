import os

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from .models import ResolveResponse
from .resolver import resolve_input

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
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/resolve", response_model=ResolveResponse)
async def resolve(input: str = Query(..., min_length=1, max_length=500)) -> ResolveResponse:
    return await resolve_input(input)
