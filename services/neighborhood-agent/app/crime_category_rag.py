from __future__ import annotations

import math
import re
import threading
from dataclasses import dataclass
from typing import Any

import httpx
from langchain_openai import OpenAIEmbeddings

from app.config import settings


@dataclass
class CrimeCategoryDoc:
    category: str
    count: int
    text: str
    aliases: set[str]
    vector: list[float]


@dataclass
class CrimeCategoryCandidate:
    category: str
    count: int
    score: float
    reason: str


@dataclass
class CrimeCategoryResolveResult:
    resolved: bool
    categories: list[str]
    candidates: list[CrimeCategoryCandidate]


_CATEGORY_ALIASES: dict[str, list[str]] = {
    "PETIT LARCENY": ["petit larceny", "petty larceny", "petty theft", "minor theft", "轻微盗窃", "轻盗", "小偷盗", "小偷窃", "偷盗", "盗窃", "偷窃"],
    "GRAND LARCENY": ["grand larceny", "grand theft", "major theft", "重大盗窃", "重盗", "偷盗", "盗窃", "偷窃"],
    "OTHER OFFENSES RELATED TO THEFT": ["theft related offenses", "other theft", "other offenses related to theft", "盗窃相关", "偷盗相关", "偷盗", "盗窃", "偷窃"],
    "GRAND LARCENY OF MOTOR VEHICLE": ["grand larceny of motor vehicle", "motor vehicle theft", "auto theft", "car theft", "vehicle theft", "偷车", "车辆盗窃", "机动车盗窃", "汽车盗窃", "偷盗", "盗窃"],
    "ROBBERY": ["robbery", "抢劫", "劫案"],
    "BURGLARY": ["burglary", "break in", "breaking and entering", "入室盗窃", "入室盗窃案", "入室行窃"],
    "ASSAULT 3 & RELATED OFFENSES": ["assault", "assault related offenses", "攻击", "袭击", "殴打", "伤害"],
    "FELONY ASSAULT": ["felony assault", "serious assault", "重罪袭击", "严重袭击", "攻击", "袭击", "殴打"],
    "HARRASSMENT 2": ["harassment", "harrassment", "骚扰", "骚扰案"],
    "DANGEROUS DRUGS": ["dangerous drugs", "drug offense", "drugs", "毒品", "涉毒", "毒品犯罪"],
    "DANGEROUS WEAPONS": ["dangerous weapons", "weapon offense", "weapons", "武器", "危险武器", "涉武器"],
    "VEHICLE AND TRAFFIC LAWS": ["vehicle and traffic laws", "traffic", "traffic violation", "交通违法", "交通违规", "交通法规"],
}


def _norm_text(value: str) -> str:
    s = value.strip().lower()
    s = re.sub(r"[^a-z0-9\u4e00-\u9fff\s&-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _collapse_key(value: str) -> str:
    return re.sub(r"[\s&-]+", "", _norm_text(value))


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


def _extract_query_terms(query_text: str) -> str:
    # Area names and filler words add noise to category embeddings. Keep the
    # original query as fallback, but strip high-frequency non-category terms.
    text = _norm_text(query_text)
    for word in (
        "inwood", "area", "区域", "这片", "这个", "多少", "案例", "案件", "犯罪", "情况",
        "类型", "有哪些", "有什么", "有多少", "的", "呢", "how many", "what type",
    ):
        text = text.replace(word, " ")
    return re.sub(r"\s+", " ", text).strip() or query_text.strip()


class CrimeCategoryRag:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._docs: list[CrimeCategoryDoc] = []
        self._alias_index: dict[str, list[CrimeCategoryDoc]] = {}
        self._embedder = OpenAIEmbeddings(
            model=settings.crime_category_rag_embedding_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )

    def _fetch_categories(self) -> list[tuple[str, int]]:
        args = {
            "target_table": "app_crime_incident_snapshot",
            "purpose": "analysis",
            "sql": (
                "SELECT offense_category, COUNT(*) AS incident_count "
                "FROM app_crime_incident_snapshot "
                "WHERE offense_category IS NOT NULL "
                "GROUP BY offense_category "
                "ORDER BY incident_count DESC "
                "LIMIT 50"
            ),
            "params": {},
            "max_rows": 50,
        }
        with httpx.Client(timeout=settings.request_timeout_seconds) as client:
            response = client.post(
                f"{settings.mcp_safety_url.rstrip('/')}/tools/execute_readonly_sql",
                json={"session_id": None, "arguments": args},
            )
            response.raise_for_status()
            payload: dict[str, Any] = response.json() or {}
        rows = payload.get("data") or []
        categories: list[tuple[str, int]] = []
        for row in rows:
            category = str(row.get("offense_category") or "").strip()
            if not category:
                continue
            try:
                count = int(row.get("incident_count") or 0)
            except (TypeError, ValueError):
                count = 0
            categories.append((category, count))
        return categories

    def _load_docs(self) -> None:
        categories = self._fetch_categories()
        texts: list[str] = []
        meta: list[tuple[str, int, set[str]]] = []
        for category, count in categories:
            aliases = {_norm_text(category), _collapse_key(category)}
            for alias in _CATEGORY_ALIASES.get(category.upper(), []):
                aliases.add(_norm_text(alias))
                aliases.add(_collapse_key(alias))
            aliases = {a for a in aliases if a}
            text = f"{category}. aliases: {', '.join(sorted(aliases))}. count: {count}"
            texts.append(text)
            meta.append((category, count, aliases))

        vectors = self._embedder.embed_documents(texts) if texts and settings.openai_api_key else [[] for _ in texts]
        self._docs = [
            CrimeCategoryDoc(
                category=meta[i][0],
                count=meta[i][1],
                aliases=meta[i][2],
                text=texts[i],
                vector=list(vectors[i]) if vectors else [],
            )
            for i in range(len(texts))
        ]
        index: dict[str, list[CrimeCategoryDoc]] = {}
        for doc in self._docs:
            for alias in doc.aliases:
                index.setdefault(alias, []).append(doc)
        self._alias_index = index

    def _ensure_loaded(self) -> None:
        if self._docs:
            return
        with self._lock:
            if not self._docs:
                self._load_docs()

    def _resolve_lexical(self, query_text: str) -> CrimeCategoryResolveResult | None:
        collapsed = _collapse_key(query_text)
        if not collapsed:
            return None
        matched_aliases: list[tuple[str, list[CrimeCategoryDoc]]] = []
        for alias, docs in self._alias_index.items():
            if len(alias) < 2:
                continue
            if alias == collapsed or alias in collapsed:
                matched_aliases.append((alias, docs))
        if not matched_aliases:
            return None
        # Prefer the most specific phrase. For example "入室盗窃" should map
        # to BURGLARY instead of also pulling every generic "盗窃" category.
        max_len = max(len(alias) for alias, _ in matched_aliases)
        matches: dict[str, CrimeCategoryCandidate] = {}
        for alias, docs in matched_aliases:
            if len(alias) < max_len:
                continue
            for doc in docs:
                matches[doc.category] = CrimeCategoryCandidate(doc.category, doc.count, 1.0, f"alias:{alias}")
        if matches:
            candidates = sorted(matches.values(), key=lambda item: (-item.score, -item.count, item.category))
            return CrimeCategoryResolveResult(True, [c.category for c in candidates], candidates)
        return None

    def resolve(self, query_text: str) -> CrimeCategoryResolveResult:
        text = query_text.strip()
        if not text:
            return CrimeCategoryResolveResult(False, [], [])
        self._ensure_loaded()
        if not self._docs:
            return CrimeCategoryResolveResult(False, [], [])

        lexical = self._resolve_lexical(text)
        if lexical is not None:
            return lexical

        if not settings.openai_api_key:
            return CrimeCategoryResolveResult(False, [], [])
        query_terms = _extract_query_terms(text)
        qvec = self._embedder.embed_query(f"{query_terms}\nnormalized: {_norm_text(query_terms)}")
        scored = [
            CrimeCategoryCandidate(doc.category, doc.count, _cosine(list(qvec), doc.vector), "embedding")
            for doc in self._docs
            if doc.vector
        ]
        scored.sort(key=lambda item: item.score, reverse=True)
        top = scored[: max(1, settings.crime_category_rag_top_k)]
        if not top:
            return CrimeCategoryResolveResult(False, [], [])
        top1 = top[0]
        top2 = top[1] if len(top) > 1 else None
        margin = top1.score - top2.score if top2 else 1.0
        if top1.score >= settings.crime_category_rag_min_similarity and margin >= settings.crime_category_rag_min_margin:
            return CrimeCategoryResolveResult(True, [top1.category], top)
        return CrimeCategoryResolveResult(False, [], top)


_resolver: CrimeCategoryRag | None = None


def get_crime_category_resolver() -> CrimeCategoryRag:
    global _resolver
    if _resolver is None:
        _resolver = CrimeCategoryRag()
    return _resolver
