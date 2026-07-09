from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, date, datetime

import httpx

from wikimedia_search.apis.http_json import ApiJsonError


class GoogleTrendsConfigError(Exception):
    """Raised when the Google Trends provider is not configured."""


@dataclass(frozen=True)
class GoogleTrendsPoint:
    date: date
    timestamp: int
    value: int


@dataclass(frozen=True)
class GoogleTrendsPayload:
    raw_json: dict
    request_url: str
    stored_request_url: str
    query: str
    start: str
    end: str
    points: list[GoogleTrendsPoint]


def subtract_months(value: date, months: int) -> date:
    month_index = value.month - months
    year = value.year + (month_index - 1) // 12
    month = (month_index - 1) % 12 + 1
    month_lengths = [
        31,
        29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    ]
    day = min(value.day, month_lengths[month - 1])
    return date(year, month, day)


def google_trends_dates() -> tuple[str, str]:
    today = date.today()
    start = subtract_months(today, 6)
    return start.isoformat(), today.isoformat()


def trend_query_for_title(title: str) -> str:
    return f'"{title}"'


def serpapi_key() -> str:
    key = os.getenv("SERPAPI_API_KEY")
    if not key:
        raise GoogleTrendsConfigError("SERPAPI_API_KEY is not configured.")

    return key


def timeline_value(point: dict) -> int | None:
    values = point.get("values")
    if not isinstance(values, list) or not values:
        return None

    first_value = values[0]
    if not isinstance(first_value, dict):
        return None

    value = first_value.get("value")
    if isinstance(value, list):
        value = value[0] if value else None

    if value is None:
        value = first_value.get("extracted_value")

    return int(value) if value is not None else None


def parse_timeline_data(data: dict) -> list[GoogleTrendsPoint]:
    timeline = data.get("interest_over_time", {}).get("timeline_data")
    if not isinstance(timeline, list):
        raise ApiJsonError("SerpAPI Google Trends response did not include interest_over_time.timeline_data.")

    points: list[GoogleTrendsPoint] = []
    for point in timeline:
        if not isinstance(point, dict):
            continue

        timestamp_value = point.get("timestamp")
        value = timeline_value(point)
        if timestamp_value is None or value is None:
            continue

        timestamp = int(timestamp_value)
        points.append(
            GoogleTrendsPoint(
                date=datetime.fromtimestamp(timestamp, tz=UTC).date(),
                timestamp=timestamp,
                value=value,
            )
        )

    if not points:
        raise ApiJsonError("SerpAPI Google Trends response contained no usable daily timeline points.")

    return points


def assert_daily_points(points: list[GoogleTrendsPoint]) -> None:
    if len(points) < 2:
        raise ApiJsonError("SerpAPI Google Trends response did not include enough points to verify daily cadence.")

    deltas = [
        points[index].timestamp - points[index - 1].timestamp
        for index in range(1, len(points))
    ]
    non_daily = [delta for delta in deltas if delta != 86400]
    if non_daily:
        raise ApiJsonError(
            "SerpAPI Google Trends response is not daily; "
            f"observed timestamp deltas include {sorted(set(non_daily))}."
        )


async def fetch_google_trends_timeseries(
    *,
    query_title: str,
    client: httpx.AsyncClient,
) -> GoogleTrendsPayload:
    query = trend_query_for_title(query_title)
    start, end = google_trends_dates()
    base_url = "https://serpapi.com/search.json"
    params = {
        "engine": "google_trends",
        "q": query,
        "data_type": "TIMESERIES",
        "cat": "0",
        "date": f"{start} {end}",
        "api_key": serpapi_key(),
    }
    request = client.build_request("GET", base_url, params=params)
    response = await client.send(request)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ApiJsonError("SerpAPI Google Trends response was not a JSON object.")

    points = parse_timeline_data(data)
    assert_daily_points(points)

    stored_request = client.build_request(
        "GET",
        base_url,
        params={**params, "api_key": "REDACTED"},
    )
    return GoogleTrendsPayload(
        raw_json=data,
        request_url=str(request.url),
        stored_request_url=str(stored_request.url),
        query=query,
        start=start,
        end=end,
        points=points,
    )
