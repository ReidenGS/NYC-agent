from __future__ import annotations

import importlib
import os
from collections.abc import Iterable

import pytest
from sqlalchemy import text

from tests.conftest import add_service_to_path


def _require_openai_key() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is required for live embedding recall-rate tests.")


def _ratio(ok: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return ok / total


def _threshold_from_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _area_variant_cases(rows: Iterable[tuple[str, str]]) -> list[tuple[str, str, str]]:
    # (query, expected_area_id, canonical_name)
    cases: list[tuple[str, str, str]] = []
    by_name = {name: area_id for area_id, name in rows}
    for name, area_id in by_name.items():
        cases.append((name.lower(), area_id, name))
        cases.append((f"{name} nyc", area_id, name))
        if name == "Long Island City":
            cases.append(("LIC", area_id, name))
            cases.append(("Long Island Cty", area_id, name))
        if name == "Greenpoint":
            cases.append(("green point", area_id, name))
    return cases


def _transit_variant_cases(stop_id: str, stop_name: str) -> list[str]:
    lowered = stop_name.lower()
    variants = [lowered, f"{stop_name} station"]
    if "blvd" in lowered:
        variants.append(lowered.replace("blvd", "boulevard"))
    if "sq" in lowered:
        variants.append(lowered.replace("sq", "square"))
    # stable de-dup
    out: list[str] = []
    seen = set()
    for item in variants:
        key = " ".join(item.split())
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def test_area_rag_db_recall_rate_report(pg_engine) -> None:
    _require_openai_key()
    min_hit_rate = _threshold_from_env("RAG_AREA_MIN_HIT_RATE", 0.70)

    with pg_engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT area_id, area_name
                FROM app_area_dimension
                WHERE area_name IN ('Astoria', 'Long Island City', 'Williamsburg', 'Greenpoint')
                ORDER BY area_id
                """
            )
        ).fetchall()
    if not rows:
        pytest.skip("No seed area rows found for area RAG recall-rate test.")

    add_service_to_path("orchestrator-agent")
    mod = importlib.import_module("app.area_rag")
    mod._resolver = None
    resolver = mod.get_area_resolver()

    cases = _area_variant_cases([(str(aid), str(name)) for aid, name in rows])
    ok = 0
    failures: list[str] = []
    for query_text, expected_area_id, canonical_name in cases:
        result = resolver.resolve(query_text)
        matched = bool(result.resolved and result.area_id == expected_area_id)
        if matched:
            ok += 1
        else:
            failures.append(
                f"{query_text!r} -> expected {canonical_name}({expected_area_id}), got "
                f"resolved={result.resolved}, area_id={result.area_id}, area_name={result.area_name}"
            )

    rate = _ratio(ok, len(cases))
    assert rate >= min_hit_rate, (
        f"Area RAG recall hit-rate too low: {ok}/{len(cases)}={rate:.2%}, "
        f"threshold={min_hit_rate:.0%}; failures: {failures[:6]}"
    )


def test_transit_rag_db_recall_rate_report(pg_engine) -> None:
    _require_openai_key()
    min_hit_rate = _threshold_from_env("RAG_TRANSIT_MIN_HIT_RATE", 0.70)

    with pg_engine.connect() as conn:
        stop = conn.execute(
            text(
                """
                SELECT stop_id, stop_name
                FROM app_transit_stop_dimension
                WHERE stop_name ILIKE '%Astoria Blvd%'
                   OR stop_name ILIKE '%Times Sq%'
                   OR stop_name ILIKE '%Times Square%'
                ORDER BY
                  CASE WHEN stop_name ILIKE '%Astoria Blvd%' THEN 0 ELSE 1 END,
                  stop_id
                LIMIT 1
                """
            )
        ).first()
        stop_ids_same_name: set[str] = set()
        if stop is not None:
            stop_ids_same_name = {
                str(r[0]) for r in conn.execute(
                    text(
                        """
                        SELECT stop_id
                        FROM app_transit_stop_dimension
                        WHERE stop_name = :stop_name
                        """
                    ),
                    {"stop_name": str(stop[1])},
                ).fetchall()
            }
    if stop is None:
        pytest.skip("No suitable transit stop found for transit RAG recall-rate test.")

    stop_id = str(stop[0])
    stop_name = str(stop[1])

    add_service_to_path("transit-agent")
    mod = importlib.import_module("app.transit_rag")
    mod._resolver = None
    resolver = mod.get_transit_resolver()

    variants = _transit_variant_cases(stop_id, stop_name)
    ok = 0
    failures: list[str] = []
    for query_text in variants:
        result = resolver.resolve(query_text)
        matched = bool(
            result.resolved
            and result.entity_id is not None
            and str(result.entity_id) in stop_ids_same_name
        )
        if matched:
            ok += 1
        else:
            failures.append(
                f"{query_text!r} -> expected {stop_id}({stop_name}), got "
                f"resolved={result.resolved}, entity_id={result.entity_id}, name={result.name}"
            )

    rate = _ratio(ok, len(variants))
    assert rate >= min_hit_rate, (
        f"Transit RAG recall hit-rate too low: {ok}/{len(variants)}={rate:.2%}, "
        f"threshold={min_hit_rate:.0%}; failures: {failures[:6]}"
    )
