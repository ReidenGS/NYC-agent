from __future__ import annotations

import importlib
import os

import pytest
from sqlalchemy import text

from tests.conftest import add_service_to_path


pytestmark = pytest.mark.integration


def _require_openai_key() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is required for live embedding RAG recall tests.")


def test_area_rag_recalls_db_area_name_variants(pg_engine) -> None:
    """Read real area names from DB and test non-exact variants can resolve back."""
    _require_openai_key()

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
        pytest.skip("No seed area names found in app_area_dimension.")

    expected_by_name = {str(name): str(area_id) for area_id, name in rows}

    add_service_to_path("orchestrator-agent")
    mod = importlib.import_module("app.area_rag")
    mod._resolver = None  # isolate from previous tests
    resolver = mod.get_area_resolver()

    variant_cases: list[tuple[str, str]] = []
    if "Astoria" in expected_by_name:
        variant_cases.extend([
            ("Astoria NYC", "Astoria"),
            ("astoria queens", "Astoria"),
        ])
    if "Long Island City" in expected_by_name:
        variant_cases.extend([
            ("LIC", "Long Island City"),
            ("Long Island Cty", "Long Island City"),
        ])
    if "Williamsburg" in expected_by_name:
        variant_cases.append(("williamsburg brooklyn", "Williamsburg"))
    if "Greenpoint" in expected_by_name:
        variant_cases.append(("green point", "Greenpoint"))

    if not variant_cases:
        pytest.skip("No supported variant cases available from current DB rows.")

    failures: list[str] = []
    for query_text, canonical_name in variant_cases:
        result = resolver.resolve(query_text)
        expected_id = expected_by_name[canonical_name]
        if not result.resolved or result.area_id != expected_id:
            got = f"resolved={result.resolved}, area_id={result.area_id}, area_name={result.area_name}"
            failures.append(f"{query_text!r} -> expected {canonical_name} ({expected_id}), got {got}")

    assert not failures, ";\n".join(failures)


def test_transit_rag_recalls_db_stop_name_variants(pg_engine) -> None:
    """Read real stop names from DB and test non-exact variants can resolve back."""
    _require_openai_key()

    with pg_engine.connect() as conn:
        stop = conn.execute(
            text(
                """
                SELECT stop_id, stop_name
                FROM app_transit_stop_dimension
                WHERE stop_name ILIKE '%Astoria Blvd%'
                ORDER BY stop_id
                LIMIT 1
                """
            )
        ).first()
        if stop is None:
            stop = conn.execute(
                text(
                    """
                    SELECT stop_id, stop_name
                    FROM app_transit_stop_dimension
                    WHERE stop_name ILIKE '%Times Sq%' OR stop_name ILIKE '%Times Square%'
                    ORDER BY stop_id
                    LIMIT 1
                    """
                )
            ).first()

    if stop is None:
        pytest.skip("No suitable transit stop found for variant recall test.")

    stop_id = str(stop[0])
    stop_name = str(stop[1])

    add_service_to_path("transit-agent")
    mod = importlib.import_module("app.transit_rag")
    mod._resolver = None  # isolate from previous tests
    resolver = mod.get_transit_resolver()

    variant_candidates = []
    lowered = stop_name.lower()
    variant_candidates.append(lowered)
    if "blvd" in lowered:
        variant_candidates.append(lowered.replace("blvd", "boulevard"))
    if "sq" in lowered:
        variant_candidates.append(lowered.replace("sq", "square"))
    variant_candidates.append(f"{stop_name} station")

    # Keep unique order
    seen = set()
    variants = []
    for v in variant_candidates:
        vv = " ".join(v.split())
        if vv not in seen:
            seen.add(vv)
            variants.append(vv)

    failures: list[str] = []
    for query_text in variants:
        result = resolver.resolve(query_text)
        if not result.resolved or result.entity_id != stop_id:
            got = f"resolved={result.resolved}, entity_id={result.entity_id}, name={result.name}"
            failures.append(f"{query_text!r} -> expected stop_id={stop_id} ({stop_name}), got {got}")

    assert not failures, ";\n".join(failures)

