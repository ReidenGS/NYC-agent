from __future__ import annotations

import importlib

import pytest

from tests.conftest import add_service_to_path


@pytest.fixture()
def area_rag_module():
    add_service_to_path("orchestrator-agent")
    return importlib.import_module("app.area_rag")


def test_area_rag_ambiguous_query_not_forced_to_resolve(area_rag_module, monkeypatch):
    resolver = area_rag_module.AreaResolverRag.__new__(area_rag_module.AreaResolverRag)
    resolver._docs = [
        area_rag_module.AreaDoc("MN0101", "Midtown", "Manhattan", "midtown", [0.80, 0.20]),
        area_rag_module.AreaDoc("MN0102", "Upper Manhattan", "Manhattan", "uptown", [0.78, 0.22]),
    ]
    resolver._lock = None
    resolver._ensure_loaded = lambda: None
    resolver._embedder = type("Embed", (), {"embed_query": lambda self, _q: [0.79, 0.21]})()

    monkeypatch.setattr(area_rag_module.settings, "area_rag_min_similarity", 0.70)
    monkeypatch.setattr(area_rag_module.settings, "area_rag_min_margin", 0.05)
    result = resolver.resolve("曼哈顿附近")
    assert result.resolved is False
    assert result.candidates and len(result.candidates) == 2

