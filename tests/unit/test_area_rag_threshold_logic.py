from __future__ import annotations

import importlib

import pytest

from tests.conftest import add_service_to_path


@pytest.fixture()
def area_rag_module():
    add_service_to_path("orchestrator-agent")
    return importlib.import_module("app.area_rag")


def test_area_rag_resolves_when_similarity_and_margin_pass(area_rag_module):
    resolver = area_rag_module.AreaResolverRag.__new__(area_rag_module.AreaResolverRag)
    resolver._docs = [
        area_rag_module.AreaDoc("QN0101", "Astoria", "Queens", "a", [1.0, 0.0]),
        area_rag_module.AreaDoc("QN0102", "LIC", "Queens", "b", [0.0, 1.0]),
    ]
    resolver._lock = None
    resolver._ensure_loaded = lambda: None
    resolver._embedder = type("Embed", (), {"embed_query": lambda self, _q: [1.0, 0.0]})()

    result = resolver.resolve("Astoria")
    assert result.resolved is True
    assert result.area_id == "QN0101"
    assert result.candidates and len(result.candidates) >= 1


def test_area_rag_returns_candidates_when_margin_fails(area_rag_module, monkeypatch):
    resolver = area_rag_module.AreaResolverRag.__new__(area_rag_module.AreaResolverRag)
    resolver._docs = [
        area_rag_module.AreaDoc("A", "Area A", None, "a", [1.0, 0.0]),
        area_rag_module.AreaDoc("B", "Area B", None, "b", [0.99, 0.01]),
    ]
    resolver._lock = None
    resolver._ensure_loaded = lambda: None
    resolver._embedder = type("Embed", (), {"embed_query": lambda self, _q: [1.0, 0.0]})()

    monkeypatch.setattr(area_rag_module.settings, "area_rag_min_similarity", 0.5)
    monkeypatch.setattr(area_rag_module.settings, "area_rag_min_margin", 0.05)
    result = resolver.resolve("ambiguous")
    assert result.resolved is False
    assert result.candidates and len(result.candidates) == 2

