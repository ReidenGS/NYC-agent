from __future__ import annotations

import math
import re
import threading
from dataclasses import dataclass

import psycopg
from langchain_openai import OpenAIEmbeddings

from app.config import settings


@dataclass
class AreaDoc:
    area_id: str
    area_name: str
    borough: str | None
    text: str
    vector: list[float]


@dataclass
class AreaCandidate:
    area_id: str
    area_name: str
    borough: str | None
    score: float


@dataclass
class AreaResolveResult:
    resolved: bool
    area_id: str | None = None
    area_name: str | None = None
    score: float | None = None
    candidates: list[AreaCandidate] | None = None


def _to_sync_dsn(url: str) -> str:
    return (
        url.replace("postgresql+asyncpg://", "postgresql://")
        .replace("postgresql+psycopg://", "postgresql://")
        .replace("postgres://", "postgresql://")
    )


def _norm_text(value: str) -> str:
    s = value.strip().lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^a-z0-9\u4e00-\u9fff\s-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _collapse_key(value: str) -> str:
    return re.sub(r"[\s-]+", "", _norm_text(value))


def _area_keys(area_name: str) -> set[str]:
    norm = _norm_text(area_name)
    keys = {norm, _collapse_key(area_name)}
    words = [w for w in norm.split() if w]
    if len(words) >= 2:
        acronym = "".join(w[0] for w in words if w[0].isalnum())
        if len(acronym) >= 2:
            keys.add(acronym)
    # High-frequency NYC alias
    if norm == "long island city":
        keys.add("lic")
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


class AreaResolverRag:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._docs: list[AreaDoc] = []
        self._name_index: dict[str, list[AreaDoc]] = {}
        self._embedder = OpenAIEmbeddings(
            model=settings.area_rag_embedding_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )

    def _load_docs(self) -> None:
        dsn = _to_sync_dsn(settings.database_url_async)
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT area_id, area_name, borough
                    FROM app_area_dimension
                    WHERE area_name IS NOT NULL AND area_name <> ''
                    ORDER BY area_id
                    """
                )
                rows = cur.fetchall()

        texts: list[str] = []
        meta: list[tuple[str, str, str | None]] = []
        for area_id, area_name, borough in rows:
            name = str(area_name)
            b = str(borough) if borough else None
            text = f"{name}. borough: {b or 'unknown'}. normalized: {_norm_text(name)}"
            texts.append(text)
            meta.append((str(area_id), name, b))

        vectors = self._embedder.embed_documents(texts) if texts else []
        self._docs = [
            AreaDoc(
                area_id=meta[i][0],
                area_name=meta[i][1],
                borough=meta[i][2],
                text=texts[i],
                vector=list(vectors[i]),
            )
            for i in range(len(texts))
        ]
        index: dict[str, list[AreaDoc]] = {}
        for doc in self._docs:
            for key in _area_keys(doc.area_name):
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
        index: dict[str, list[AreaDoc]] = {}
        for doc in getattr(self, "_docs", []) or []:
            for key in _area_keys(doc.area_name):
                index.setdefault(key, []).append(doc)
        self._name_index = index

    def _resolve_lexical(self, query_text: str) -> AreaResolveResult | None:
        key = _collapse_key(query_text)
        if not key:
            return None
        self._ensure_name_index()
        hits = self._name_index.get(key, [])
        if len(hits) == 1:
            hit = hits[0]
            return AreaResolveResult(
                resolved=True,
                area_id=hit.area_id,
                area_name=hit.area_name,
                score=1.0,
                candidates=[AreaCandidate(hit.area_id, hit.area_name, hit.borough, 1.0)],
            )
        return None

    def resolve(self, query_text: str) -> AreaResolveResult:
        text = query_text.strip()
        if not text:
            return AreaResolveResult(resolved=False)
        self._ensure_loaded()
        if not self._docs:
            return AreaResolveResult(resolved=False)
        lexical = self._resolve_lexical(text)
        if lexical is not None:
            return lexical

        qvec = self._embedder.embed_query(f"{text}\nnormalized: {_norm_text(text)}")
        scored: list[AreaCandidate] = []
        for doc in self._docs:
            score = _cosine(list(qvec), doc.vector)
            scored.append(AreaCandidate(doc.area_id, doc.area_name, doc.borough, score))
        scored.sort(key=lambda x: x.score, reverse=True)

        top_k = max(1, settings.area_rag_top_k)
        top = scored[:top_k]
        if not top:
            return AreaResolveResult(resolved=False)

        top1 = top[0]
        top2 = top[1] if len(top) > 1 else None
        margin = top1.score - top2.score if top2 else 1.0
        if top1.score >= settings.area_rag_min_similarity and margin >= settings.area_rag_min_margin:
            return AreaResolveResult(
                resolved=True,
                area_id=top1.area_id,
                area_name=top1.area_name,
                score=top1.score,
                candidates=top,
            )
        return AreaResolveResult(resolved=False, candidates=top)


_resolver: AreaResolverRag | None = None


def get_area_resolver() -> AreaResolverRag:
    global _resolver
    if _resolver is None:
        _resolver = AreaResolverRag()
    return _resolver
