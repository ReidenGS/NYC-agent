from __future__ import annotations

import importlib

import pytest

from tests.conftest import add_service_to_path


@pytest.fixture()
def transit_rag_module(monkeypatch):
    add_service_to_path("transit-agent")
    mod = importlib.import_module("app.transit_rag")

    class DummyEmbedder:
        def embed_documents(self, texts):
            return [[float(i + 1), 1.0] for i in range(len(texts))]

        def embed_query(self, _):
            return [1.0, 1.0]

    class DummyCursor:
        def __init__(self):
            self._last_sql = ""

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql):
            self._last_sql = sql

        def fetchall(self):
            if "app_transit_stop_dimension" in self._last_sql:
                return [("R16", "Astoria Blvd", "subway", 40.77, -73.92)]
            return [("QN0101", "Astoria", "Queens", 40.7644, -73.9235)]

    class DummyConn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def cursor(self):
            return DummyCursor()

    monkeypatch.setattr(mod, "OpenAIEmbeddings", lambda **_: DummyEmbedder())
    monkeypatch.setattr(mod.psycopg, "connect", lambda _dsn: DummyConn())
    return mod


def test_transit_rag_builds_fused_stop_and_area_docs(transit_rag_module):
    resolver = transit_rag_module.TransitResolverRag()
    resolver._load_docs()
    assert resolver.doc_count() == 2
    kinds = {d.kind for d in resolver._docs}
    assert kinds == {"stop", "area"}


def test_transit_rag_empty_query_is_unresolved(transit_rag_module):
    resolver = transit_rag_module.TransitResolverRag.__new__(transit_rag_module.TransitResolverRag)
    resolver._docs = []
    resolver._ensure_loaded = lambda: None
    result = resolver.resolve("")
    assert result.resolved is False

