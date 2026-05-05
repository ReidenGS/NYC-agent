from __future__ import annotations

import importlib

from tests.conftest import add_service_to_path


def test_transit_rag_resolution_contract_fields_present():
    add_service_to_path("transit-agent")
    mod = importlib.import_module("app.transit_rag")

    resolver = mod.TransitResolverRag.__new__(mod.TransitResolverRag)
    resolver._docs = [
        mod.TransitDoc("stop", "R16", "Astoria Blvd", "subway", None, 40.77, -73.92, "x", [1.0, 0.0]),
        mod.TransitDoc("stop", "R20", "Times Sq", "subway", None, 40.75, -73.99, "y", [0.0, 1.0]),
    ]
    resolver._lock = None
    resolver._ensure_loaded = lambda: None
    resolver._embedder = type("Embed", (), {"embed_query": lambda self, _q: [1.0, 0.0]})()

    result = resolver.resolve("Astoria Blvd")
    assert result.resolved is True
    assert result.kind == "stop"
    assert result.entity_id == "R16"
    assert isinstance(result.score, float)
    assert result.candidates and isinstance(result.candidates, list)
    first = result.candidates[0]
    assert first.name
    assert first.entity_id
    assert isinstance(first.score, float)

