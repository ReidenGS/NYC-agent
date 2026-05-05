"""Transit endpoint resolver — embedding RAG over MTA stops + NYC NTAs.

Mirrors orchestrator-agent/app/area_rag.py:
- Process-local memory list (no pgvector).
- OpenAIEmbeddings (text-embedding-3-small).
- Double-threshold acceptance: min_similarity AND min_margin (top1 - top2).

Corpus is fused: MTA stop_dimension (~496) + NTA app_area_dimension (~262).
Each doc carries `kind ∈ {"stop","area"}` so caller can decide whether the
hit is a stop_id or area_id when it routes to mcp-transit.
"""
from __future__ import annotations

import math
import re
import threading
from dataclasses import dataclass
from typing import Literal

import psycopg
from langchain_openai import OpenAIEmbeddings

from app.config import settings


EntityKind = Literal["stop", "area"]


@dataclass
class TransitDoc:
    kind: EntityKind
    entity_id: str
    name: str
    mode: str | None
    borough: str | None
    latitude: float | None
    longitude: float | None
    text: str
    vector: list[float]


@dataclass
class TransitCandidate:
    kind: EntityKind
    entity_id: str
    name: str
    mode: str | None
    borough: str | None
    latitude: float | None
    longitude: float | None
    score: float


@dataclass
class TransitResolveResult:
    resolved: bool
    kind: EntityKind | None = None
    entity_id: str | None = None
    name: str | None = None
    mode: str | None = None
    borough: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    score: float | None = None
    candidates: list[TransitCandidate] | None = None


def _to_sync_dsn(url: str) -> str:
    return (
        url.replace("postgresql+asyncpg://", "postgresql://")
        .replace("postgresql+psycopg://", "postgresql://")
        .replace("postgres://", "postgresql://")
    )


def _norm_text(value: str) -> str:
    s = value.strip().lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^a-z0-9一-鿿\s-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


_ABBREV_MAP = {
    "blvd": "boulevard",
    "sq": "square",
    "st": "street",
    "ave": "avenue",
    "av": "avenue",
}


def _expand_abbrev(norm: str) -> str:
    words = []
    for w in norm.split():
        words.append(_ABBREV_MAP.get(w, w))
    return " ".join(words)


def _collapse_key(value: str) -> str:
    norm = _norm_text(value)
    norm = _expand_abbrev(norm)
    return re.sub(r"[\s-]+", "", norm)


def _doc_keys(name: str) -> set[str]:
    norm = _norm_text(name)
    expanded = _expand_abbrev(norm)
    keys = {
        re.sub(r"[\s-]+", "", norm),
        re.sub(r"[\s-]+", "", expanded),
    }
    return {k for k in keys if k}


def _cosine(a: list[float], b: list[float]) -> float:
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


class TransitResolverRag:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._docs: list[TransitDoc] = []
        self._name_index: dict[str, list[TransitDoc]] = {}
        self._embedder = OpenAIEmbeddings(
            model=settings.transit_rag_embedding_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )

    def _load_docs(self) -> None:
        dsn = _to_sync_dsn(settings.database_url_sql)
        rows: list[tuple[EntityKind, str, str, str | None, str | None, float | None, float | None]] = []
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT stop_id, stop_name, mode, latitude, longitude
                    FROM app_transit_stop_dimension
                    WHERE stop_name IS NOT NULL AND stop_name <> ''
                    ORDER BY stop_id
                    """
                )
                for stop_id, stop_name, mode, lat, lon in cur.fetchall():
                    rows.append(
                        ("stop", str(stop_id), str(stop_name), str(mode) if mode else None, None, float(lat) if lat is not None else None, float(lon) if lon is not None else None)
                    )
                cur.execute(
                    """
                    SELECT area_id, area_name, borough,
                           ST_Y(ST_Centroid(geom)) AS lat,
                           ST_X(ST_Centroid(geom)) AS lon
                    FROM app_area_dimension
                    WHERE area_name IS NOT NULL AND area_name <> ''
                    ORDER BY area_id
                    """
                )
                for area_id, area_name, borough, lat, lon in cur.fetchall():
                    rows.append(
                        ("area", str(area_id), str(area_name), None, str(borough) if borough else None, float(lat) if lat is not None else None, float(lon) if lon is not None else None)
                    )

        texts: list[str] = []
        for kind, _id, name, mode, borough, _lat, _lon in rows:
            if kind == "stop":
                texts.append(f"{name}, NYC subway/bus stop. mode: {mode or 'unknown'}. normalized: {_norm_text(name)}")
            else:
                texts.append(f"{name}, NYC neighborhood in {borough or 'unknown'} borough. normalized: {_norm_text(name)}")

        vectors = self._embedder.embed_documents(texts) if texts else []
        self._docs = [
            TransitDoc(
                kind=rows[i][0],
                entity_id=rows[i][1],
                name=rows[i][2],
                mode=rows[i][3],
                borough=rows[i][4],
                latitude=rows[i][5],
                longitude=rows[i][6],
                text=texts[i],
                vector=list(vectors[i]),
            )
            for i in range(len(texts))
        ]
        index: dict[str, list[TransitDoc]] = {}
        for doc in self._docs:
            for key in _doc_keys(doc.name):
                index.setdefault(key, []).append(doc)
        self._name_index = index

    def _ensure_loaded(self) -> None:
        if self._docs:
            return
        with self._lock:
            if not self._docs:
                self._load_docs()

    def _ensure_name_index(self) -> None:
        if hasattr(self, "_name_index") and self._name_index:
            return
        index: dict[str, list[TransitDoc]] = {}
        for doc in getattr(self, "_docs", []) or []:
            for key in _doc_keys(doc.name):
                index.setdefault(key, []).append(doc)
        self._name_index = index

    def is_loaded(self) -> bool:
        return bool(self._docs)

    def doc_count(self) -> int:
        return len(self._docs)

    def _resolve_lexical(self, query_text: str) -> TransitResolveResult | None:
        key = _collapse_key(query_text)
        if not key:
            return None
        self._ensure_name_index()
        hits = self._name_index.get(key, [])
        if len(hits) == 1:
            hit = hits[0]
            return TransitResolveResult(
                resolved=True,
                kind=hit.kind,
                entity_id=hit.entity_id,
                name=hit.name,
                mode=hit.mode,
                borough=hit.borough,
                latitude=hit.latitude,
                longitude=hit.longitude,
                score=1.0,
                candidates=[
                    TransitCandidate(
                        kind=hit.kind,
                        entity_id=hit.entity_id,
                        name=hit.name,
                        mode=hit.mode,
                        borough=hit.borough,
                        latitude=hit.latitude,
                        longitude=hit.longitude,
                        score=1.0,
                    )
                ],
            )
        return None

    def resolve(self, query_text: str) -> TransitResolveResult:
        text = (query_text or "").strip()
        if not text:
            return TransitResolveResult(resolved=False)
        self._ensure_loaded()
        if not self._docs:
            return TransitResolveResult(resolved=False)
        lexical = self._resolve_lexical(text)
        if lexical is not None:
            return lexical

        qvec = self._embedder.embed_query(f"{text}\nnormalized: {_norm_text(text)}")
        scored: list[TransitCandidate] = []
        for doc in self._docs:
            score = _cosine(list(qvec), doc.vector)
            scored.append(
                TransitCandidate(
                    kind=doc.kind,
                    entity_id=doc.entity_id,
                    name=doc.name,
                    mode=doc.mode,
                    borough=doc.borough,
                    latitude=doc.latitude,
                    longitude=doc.longitude,
                    score=score,
                )
            )
        scored.sort(key=lambda x: x.score, reverse=True)

        top_k = max(1, settings.transit_rag_top_k)
        top = scored[:top_k]
        if not top:
            return TransitResolveResult(resolved=False)

        top1 = top[0]
        top2 = top[1] if len(top) > 1 else None
        margin = top1.score - top2.score if top2 else 1.0
        if top1.score >= settings.transit_rag_min_similarity and margin >= settings.transit_rag_min_margin:
            return TransitResolveResult(
                resolved=True,
                kind=top1.kind,
                entity_id=top1.entity_id,
                name=top1.name,
                mode=top1.mode,
                borough=top1.borough,
                latitude=top1.latitude,
                longitude=top1.longitude,
                score=top1.score,
                candidates=top,
            )
        return TransitResolveResult(resolved=False, candidates=top)


_resolver: TransitResolverRag | None = None


def get_transit_resolver() -> TransitResolverRag:
    global _resolver
    if _resolver is None:
        _resolver = TransitResolverRag()
    return _resolver
