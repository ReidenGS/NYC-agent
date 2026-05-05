from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

from tests.conftest import add_service_to_path


@pytest.fixture()
def area_rag_module(monkeypatch):
    add_service_to_path("orchestrator-agent")
    mod = importlib.import_module("app.area_rag")

    class DummyEmbedder:
        def embed_documents(self, texts):
            return [[float(i + 1), float(i + 2)] for i in range(len(texts))]

        def embed_query(self, _):
            return [1.0, 1.0]

    class DummyCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, _sql):
            return None

        def fetchall(self):
            return [
                ("QN0101", "Astoria", "Queens"),
                ("QN0102", "Long Island City", "Queens"),
            ]

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


def test_area_rag_builds_index_from_db_rows(area_rag_module):
    resolver = area_rag_module.AreaResolverRag()
    resolver._load_docs()
    assert len(resolver._docs) == 2
    assert resolver._docs[0].area_id == "QN0101"
    assert resolver._docs[1].area_name == "Long Island City"


def test_area_rag_empty_corpus_returns_unresolved(area_rag_module, monkeypatch):
    resolver = area_rag_module.AreaResolverRag()
    resolver._docs = []
    monkeypatch.setattr(resolver, "_load_docs", lambda: None)
    result = resolver.resolve("Astoria")
    assert result.resolved is False
    assert result.candidates is None

