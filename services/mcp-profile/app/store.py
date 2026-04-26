from __future__ import annotations

import json
from datetime import datetime
from threading import Lock
from typing import Any
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from nyc_agent_shared.schemas import Budget, DecisionWeights, ProfileSnapshot, TargetArea
from nyc_agent_shared.time import now_iso

AREA_FIXTURES: dict[str, TargetArea] = {
    'QN0101': TargetArea(area_id='QN0101', area_name='Astoria', borough='Queens'),
    'QN0102': TargetArea(area_id='QN0102', area_name='Long Island City', borough='Queens'),
    'BK0101': TargetArea(area_id='BK0101', area_name='Williamsburg', borough='Brooklyn'),
    'BK0102': TargetArea(area_id='BK0102', area_name='Greenpoint', borough='Brooklyn'),
    'MN0101': TargetArea(area_id='MN0101', area_name='Midtown', borough='Manhattan'),
}


def _loads_json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        return json.loads(value)
    return value


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or now_iso())


class MemoryProfileStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._profiles: dict[str, ProfileSnapshot] = {}

    def create_session(self) -> ProfileSnapshot:
        session_id = f'sess_{uuid4().hex[:16]}'
        profile = ProfileSnapshot(session_id=session_id, updated_at=now_iso())
        with self._lock:
            self._profiles[session_id] = profile
        return profile

    def get(self, session_id: str) -> ProfileSnapshot | None:
        with self._lock:
            return self._profiles.get(session_id)

    def save(self, profile: ProfileSnapshot) -> ProfileSnapshot:
        with self._lock:
            self._profiles[profile.session_id] = profile
        return profile

    def delete_session(self, session_id: str) -> bool:
        with self._lock:
            return self._profiles.pop(session_id, None) is not None


class ProfileStore:
    def __init__(self) -> None:
        self.memory = MemoryProfileStore()
        self.engine = create_engine(settings.sqlalchemy_database_url, pool_pre_ping=True, pool_size=3, max_overflow=2)

    def backend_status(self) -> dict[str, str]:
        if settings.profile_store_backend == "memory":
            return {"backend": "memory", "postgres": "disabled"}
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return {"backend": "postgres", "postgres": "ok"}
        except Exception as exc:
            return {"backend": "memory_fallback", "postgres": f"unavailable: {exc}"}

    def _db_enabled(self) -> bool:
        return settings.profile_store_backend != "memory"

    def _ensure_area(self, conn, area: TargetArea) -> None:
        conn.execute(
            text(
                """
                INSERT INTO app_area_dimension (area_id, area_name, borough)
                VALUES (:area_id, :area_name, :borough)
                ON CONFLICT (area_id) DO NOTHING
                """
            ),
            {"area_id": area.area_id, "area_name": area.area_name, "borough": area.borough or "Unknown"},
        )

    def _area(self, area_id: str | None, area_name: str | None = None, borough: str | None = None) -> TargetArea | None:
        if not area_id:
            return None
        fixture = AREA_FIXTURES.get(area_id)
        return TargetArea(area_id=area_id, area_name=area_name or (fixture.area_name if fixture else area_id), borough=borough or (fixture.borough if fixture else None))

    def _row_to_profile(self, row: Any) -> ProfileSnapshot:
        data = dict(row._mapping)
        slots = _loads_json(data.get("slots_json"), {})
        missing = _loads_json(data.get("missing_required"), [])
        area = self._area(data.get("target_area_id"), data.get("area_name"), data.get("borough"))
        budget = None
        if data.get("budget_min") is not None or data.get("budget_max") is not None:
            budget = Budget(min=float(data["budget_min"]) if data.get("budget_min") is not None else None, max=float(data["budget_max"]) if data.get("budget_max") is not None else None)
        weights = DecisionWeights(
            safety=float(data.get("weight_safety") or 0.30),
            commute=float(data.get("weight_commute") or 0.30),
            rent=float(data.get("weight_rent") or 0.20),
            convenience=float(data.get("weight_convenience") or 0.10),
            entertainment=float(data.get("weight_entertainment") or 0.10),
        )
        comparison_ids = slots.get("comparison_areas") or []
        return ProfileSnapshot(
            session_id=data["session_id"],
            target_area=area,
            target_area_id=data.get("target_area_id"),
            comparison_areas=[self._area(str(a)) for a in comparison_ids if self._area(str(a))],
            budget=budget,
            target_destination=data.get("target_destination"),
            max_commute_minutes=data.get("max_commute_minutes"),
            preferences=list(slots.get("preferences") or []),
            weights=weights,
            missing_required_fields=list(missing),
            conversation_summary=str(slots.get("conversation_summary") or ""),
            last_response_refs=dict(slots.get("last_response_refs") or {}),
            updated_at=_iso(data.get("updated_at")),
        )

    def _get_db(self, session_id: str) -> ProfileSnapshot | None:
        with self.engine.begin() as conn:
            conn.execute(text(f"SET LOCAL statement_timeout = {int(settings.profile_statement_timeout_ms)}"))
            row = conn.execute(
                text(
                    """
                    SELECT p.*, a.area_name, a.borough
                    FROM app_session_profile p
                    LEFT JOIN app_area_dimension a ON a.area_id = p.target_area_id
                    WHERE p.session_id = :session_id
                    """
                ),
                {"session_id": session_id},
            ).first()
            return self._row_to_profile(row) if row else None

    def get(self, session_id: str) -> ProfileSnapshot | None:
        if self._db_enabled():
            try:
                profile = self._get_db(session_id)
                if profile:
                    return profile
            except SQLAlchemyError:
                pass
        return self.memory.get(session_id)

    def create_session(self) -> ProfileSnapshot:
        profile = self.memory.create_session()
        if not self._db_enabled():
            return profile
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO app_session_profile (session_id, missing_required, slots_json)
                        VALUES (:session_id, CAST(:missing_required AS JSONB), CAST(:slots_json AS JSONB))
                        """
                    ),
                    {
                        "session_id": profile.session_id,
                        "missing_required": json.dumps(profile.missing_required_fields),
                        "slots_json": json.dumps({}),
                    },
                )
            return self._get_db(profile.session_id) or profile
        except SQLAlchemyError:
            return profile

    def require(self, session_id: str) -> ProfileSnapshot:
        profile = self.get(session_id)
        if profile is None:
            raise KeyError(session_id)
        return profile

    def _save_profile_db(self, profile: ProfileSnapshot) -> ProfileSnapshot:
        if profile.target_area:
            area = profile.target_area
        elif profile.target_area_id:
            area = self._area(profile.target_area_id)
        else:
            area = None
        slots = {
            "preferences": profile.preferences,
            "comparison_areas": [a.area_id for a in profile.comparison_areas],
            "conversation_summary": profile.conversation_summary,
            "last_response_refs": profile.last_response_refs,
        }
        with self.engine.begin() as conn:
            conn.execute(text(f"SET LOCAL statement_timeout = {int(settings.profile_statement_timeout_ms)}"))
            if area:
                self._ensure_area(conn, area)
            conn.execute(
                text(
                    """
                    UPDATE app_session_profile
                    SET target_area_id = :target_area_id,
                        budget_min = :budget_min,
                        budget_max = :budget_max,
                        target_destination = :target_destination,
                        max_commute_minutes = :max_commute_minutes,
                        weight_safety = :weight_safety,
                        weight_commute = :weight_commute,
                        weight_rent = :weight_rent,
                        weight_convenience = :weight_convenience,
                        weight_entertainment = :weight_entertainment,
                        slots_json = CAST(:slots_json AS JSONB),
                        missing_required = CAST(:missing_required AS JSONB),
                        updated_at = NOW()
                    WHERE session_id = :session_id
                    """
                ),
                {
                    "session_id": profile.session_id,
                    "target_area_id": profile.target_area_id,
                    "budget_min": profile.budget.min if profile.budget else None,
                    "budget_max": profile.budget.max if profile.budget else None,
                    "target_destination": profile.target_destination,
                    "max_commute_minutes": profile.max_commute_minutes,
                    "weight_safety": profile.weights.safety,
                    "weight_commute": profile.weights.commute,
                    "weight_rent": profile.weights.rent,
                    "weight_convenience": profile.weights.convenience,
                    "weight_entertainment": profile.weights.entertainment,
                    "slots_json": json.dumps(slots),
                    "missing_required": json.dumps(profile.missing_required_fields),
                },
            )
        return self._get_db(profile.session_id) or profile

    def _save(self, profile: ProfileSnapshot) -> ProfileSnapshot:
        profile.updated_at = now_iso()
        self.memory.save(profile)
        if self._db_enabled():
            try:
                return self._save_profile_db(profile)
            except SQLAlchemyError:
                pass
        return profile

    def patch_slots(self, session_id: str, slots: dict) -> ProfileSnapshot:
        profile = self.require(session_id)
        area_id = slots.get('target_area_id') or slots.get('target_area')
        if area_id:
            area = AREA_FIXTURES.get(str(area_id), TargetArea(area_id=str(area_id), area_name=str(area_id)))
            profile.target_area = area
            profile.target_area_id = area.area_id
            profile.missing_required_fields = [f for f in profile.missing_required_fields if f != 'target_area']
        if 'budget_monthly' in slots:
            profile.budget = Budget(max=float(slots['budget_monthly']))
        if 'target_destination' in slots:
            profile.target_destination = slots['target_destination']
        if 'max_commute_minutes' in slots:
            profile.max_commute_minutes = int(slots['max_commute_minutes'])
        if 'preferences' in slots:
            profile.preferences = list(slots['preferences'])
        return self._save(profile)

    def update_weights(self, session_id: str, weights: dict) -> ProfileSnapshot:
        profile = self.require(session_id)
        profile.weights = DecisionWeights(**weights).normalized()
        return self._save(profile)

    def update_comparison_areas(self, session_id: str, areas: list[str]) -> ProfileSnapshot:
        profile = self.require(session_id)
        profile.comparison_areas = [AREA_FIXTURES.get(a, TargetArea(area_id=a, area_name=a)) for a in areas[:5]]
        return self._save(profile)

    def save_summary(self, session_id: str, summary: str) -> ProfileSnapshot:
        profile = self.require(session_id)
        profile.conversation_summary = summary[:800]
        return self._save(profile)

    def save_last_response_refs(self, session_id: str, refs: dict) -> ProfileSnapshot:
        profile = self.require(session_id)
        profile.last_response_refs = refs
        return self._save(profile)

    def delete_session(self, session_id: str) -> bool:
        deleted_memory = self.memory.delete_session(session_id)
        if self._db_enabled():
            try:
                with self.engine.begin() as conn:
                    result = conn.execute(text("DELETE FROM app_session_profile WHERE session_id = :session_id"), {"session_id": session_id})
                return bool(result.rowcount) or deleted_memory
            except SQLAlchemyError:
                pass
        return deleted_memory


store = ProfileStore()
