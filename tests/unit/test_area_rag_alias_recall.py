from __future__ import annotations

import importlib

from tests.conftest import add_service_to_path


def _make_resolver(mod):
    resolver = mod.AreaResolverRag.__new__(mod.AreaResolverRag)
    resolver._docs = [
        mod.AreaDoc("QN0101", "Astoria", "Queens", "astoria", [1.0, 0.0]),
        mod.AreaDoc("QN0102", "Long Island City", "Queens", "lic", [0.0, 1.0]),
    ]
    resolver._lock = None
    resolver._ensure_loaded = lambda: None
    return resolver


def test_area_rag_recalls_lic_alias():
    add_service_to_path("orchestrator-agent")
    mod = importlib.import_module("app.area_rag")
    resolver = _make_resolver(mod)
    resolver._embedder = type("Embed", (), {"embed_query": lambda self, _q: [0.0, 1.0]})()
    result = resolver.resolve("LIC")
    assert result.resolved is True
    assert result.area_id == "QN0102"


def test_area_rag_case_and_whitespace_noise():
    add_service_to_path("orchestrator-agent")
    mod = importlib.import_module("app.area_rag")
    resolver = _make_resolver(mod)
    resolver._embedder = type("Embed", (), {"embed_query": lambda self, _q: [1.0, 0.0]})()
    result = resolver.resolve("  aSTORIA   ")
    assert result.resolved is True
    assert result.area_name == "Astoria"

