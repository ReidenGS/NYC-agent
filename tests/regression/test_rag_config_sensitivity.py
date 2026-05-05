from __future__ import annotations

import importlib

import pytest

from tests.conftest import add_service_to_path


@pytest.fixture()
def transit_rag_module():
    add_service_to_path("transit-agent")
    return importlib.import_module("app.transit_rag")


def test_transit_rag_threshold_change_affects_resolution(transit_rag_module, monkeypatch):
    resolver = transit_rag_module.TransitResolverRag.__new__(transit_rag_module.TransitResolverRag)
    resolver._docs = [
        transit_rag_module.TransitDoc("stop", "S1", "Astoria Blvd", "subway", None, 0, 0, "a", [1.0, 0.0]),
        transit_rag_module.TransitDoc("stop", "S2", "Astoria-Ditmars", "subway", None, 0, 0, "b", [0.96, 0.04]),
    ]
    resolver._lock = None
    resolver._ensure_loaded = lambda: None
    resolver._embedder = type("Embed", (), {"embed_query": lambda self, _q: [1.0, 0.0]})()

    monkeypatch.setattr(transit_rag_module.settings, "transit_rag_min_similarity", 0.5)
    monkeypatch.setattr(transit_rag_module.settings, "transit_rag_min_margin", 0.01)
    strict = resolver.resolve("Astoria")
    assert strict.resolved is False

    monkeypatch.setattr(transit_rag_module.settings, "transit_rag_min_margin", 0.0001)
    relaxed = resolver.resolve("Astoria")
    assert relaxed.resolved is True
    assert relaxed.entity_id == "S1"
