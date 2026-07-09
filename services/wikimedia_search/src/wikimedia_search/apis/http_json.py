from __future__ import annotations

import httpx


class ApiJsonError(Exception):
    """Raised when an external API response cannot be used as JSON."""


async def get_json(client: httpx.AsyncClient, url: str, *, params: dict | None = None) -> dict:
    response = await client.get(url, params=params)
    response.raise_for_status()
    data = response.json()

    if not isinstance(data, dict):
        raise ApiJsonError("API response was not a JSON object.")

    return data


def assert_mediawiki_response(data: dict) -> None:
    if "error" in data:
        error = data["error"]
        raise ApiJsonError(error.get("info") or error.get("code") or "MediaWiki API error.")
