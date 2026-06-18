"""Offline tests for LivePlacesClient via httpx.MockTransport — zero network.

Proves request-building (field mask + circle), New-API response normalization, pagination across
nextPageToken, and (tile,keyword) caching (no second network call). Pytest never sleeps: the
pagination-token backoff only triggers on a live 400, and the mock returns valid pages immediately.
"""

from __future__ import annotations

import httpx

from leadscout.cache import JsonCache
from leadscout.clients import LivePlacesClient
from leadscout.stages.discover import _raw_to_lead


def _place(pid: str, name: str) -> dict:
    return {
        "id": pid,
        "displayName": {"text": name, "languageCode": "en"},
        "primaryType": "dentist",
        "rating": 4.5,
        "userRatingCount": 120,
        "websiteUri": f"https://{pid}.example.com",
        "internationalPhoneNumber": "+91 80 1234 5678",
        "businessStatus": "OPERATIONAL",
        "formattedAddress": "MG Road, Bengaluru",
    }


def _client(handler) -> LivePlacesClient:
    transport = httpx.MockTransport(handler)
    return LivePlacesClient("test-key", client=httpx.Client(transport=transport))


def test_search_paginates_and_normalizes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        if '"pageToken"' in body:
            return httpx.Response(200, json={"places": [_place("p3", "Gamma Dental")]})
        return httpx.Response(
            200,
            json={
                "places": [_place("p1", "Alpha Dental"), _place("p2", "Beta Dental")],
                "nextPageToken": "t2",
            },
        )

    client = _client(handler)
    page = client.search(12.97, 77.59, 10.0, "dentist")

    assert len(page.results) == 3
    assert [r["place_id"] for r in page.results] == ["p1", "p2", "p3"]
    assert all(isinstance(r["name"], str) and r["name"] for r in page.results)

    lead = _raw_to_lead(page.results[0])
    assert lead.place_id == "p1"
    assert lead.name == "Alpha Dental"
    assert lead.website == "https://p1.example.com"
    assert lead.phone == "+91 80 1234 5678"


def test_search_respects_field_mask_and_circle() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["field_mask"] = request.headers.get("X-Goog-FieldMask")
        seen["api_key"] = request.headers.get("X-Goog-Api-Key")
        seen["body"] = json.loads(request.read())
        return httpx.Response(200, json={"places": [_place("p1", "Alpha Dental")]})

    client = _client(handler)
    client.search(12.97, 77.59, 80.0, "dentist")  # 80 km -> capped at 50 km

    assert seen["field_mask"] == LivePlacesClient.FIELD_MASK
    assert seen["api_key"] == "test-key"
    # Text Search (New): a circle is a locationBias, not a locationRestriction.
    circle = seen["body"]["locationBias"]["circle"]
    assert circle["radius"] == 50_000  # min(80,50)*1000
    assert circle["center"] == {"latitude": 12.97, "longitude": 77.59}
    assert seen["body"]["textQuery"] == "dentist"


def test_search_cache_prevents_refetch(tmp_path) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"places": [_place("p1", "Alpha Dental")]})

    transport = httpx.MockTransport(handler)
    client = LivePlacesClient(
        "test-key", cache=JsonCache(tmp_path), client=httpx.Client(transport=transport)
    )

    first = client.search(12.97, 77.59, 10.0, "dentist")
    second = client.search(12.97, 77.59, 10.0, "dentist")

    assert first.results == second.results
    assert calls["n"] == 1, "second call must hit cache, not the network"


def test_geocode_bbox_maps_viewport(tmp_path) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "results": [
                    {
                        "geometry": {
                            "viewport": {
                                "northeast": {"lat": 13.1, "lng": 77.8},
                                "southwest": {"lat": 12.8, "lng": 77.4},
                            }
                        }
                    }
                ],
            },
        )

    transport = httpx.MockTransport(handler)
    client = LivePlacesClient(
        "test-key", cache=JsonCache(tmp_path), client=httpx.Client(transport=transport)
    )

    bbox = client.geocode_bbox("Bengaluru")
    assert (bbox.min_lat, bbox.min_lng) == (12.8, 77.4)
    assert (bbox.max_lat, bbox.max_lng) == (13.1, 77.8)

    again = client.geocode_bbox("Bengaluru")
    assert again == bbox
    assert calls["n"] == 1, "second geocode must hit cache, not the network"
