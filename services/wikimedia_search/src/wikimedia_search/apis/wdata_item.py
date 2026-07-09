from __future__ import annotations

from dataclasses import dataclass

import httpx

from wikimedia_search.apis.http_json import assert_mediawiki_response, get_json


@dataclass(frozen=True)
class WikidataEntityPayload:
    raw_json: dict
    qid: str
    entity: dict
    labels_count: int
    descriptions_count: int
    sitelinks_count: int
    claim_groups_count: int


async def fetch_wikidata_entity(*, qid: str, client: httpx.AsyncClient) -> WikidataEntityPayload:
    data = await get_json(
        client,
        "https://www.wikidata.org/w/api.php",
        params={
            "action": "wbgetentities",
            "ids": qid,
            "props": "labels|descriptions|sitelinks|claims",
            "languages": "en",
            "format": "json",
            "origin": "*",
        },
    )
    assert_mediawiki_response(data)
    entity = data.get("entities", {}).get(qid, {})

    return WikidataEntityPayload(
        raw_json=data,
        qid=qid,
        entity=entity,
        labels_count=len(entity.get("labels", {})),
        descriptions_count=len(entity.get("descriptions", {})),
        sitelinks_count=len(entity.get("sitelinks", {})),
        claim_groups_count=len(entity.get("claims", {})),
    )
