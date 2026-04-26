from __future__ import annotations

from threading import Lock
from uuid import uuid4

from nyc_agent_shared.schemas import Budget, DecisionWeights, ProfileSnapshot, TargetArea
from nyc_agent_shared.time import now_iso

AREA_FIXTURES: dict[str, TargetArea] = {
    'QN0101': TargetArea(area_id='QN0101', area_name='Astoria', borough='Queens'),
    'QN0102': TargetArea(area_id='QN0102', area_name='Long Island City', borough='Queens'),
    'BK0101': TargetArea(area_id='BK0101', area_name='Williamsburg', borough='Brooklyn'),
    'BK0102': TargetArea(area_id='BK0102', area_name='Greenpoint', borough='Brooklyn'),
    'MN0101': TargetArea(area_id='MN0101', area_name='Midtown', borough='Manhattan'),
}


class ProfileStore:
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

    def require(self, session_id: str) -> ProfileSnapshot:
        profile = self.get(session_id)
        if profile is None:
            raise KeyError(session_id)
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
            value = float(slots['budget_monthly'])
            profile.budget = Budget(max=value)
        if 'target_destination' in slots:
            profile.target_destination = slots['target_destination']
        if 'max_commute_minutes' in slots:
            profile.max_commute_minutes = int(slots['max_commute_minutes'])
        if 'preferences' in slots:
            profile.preferences = list(slots['preferences'])
        profile.updated_at = now_iso()
        with self._lock:
            self._profiles[session_id] = profile
        return profile

    def update_weights(self, session_id: str, weights: dict) -> ProfileSnapshot:
        profile = self.require(session_id)
        profile.weights = DecisionWeights(**weights).normalized()
        profile.updated_at = now_iso()
        with self._lock:
            self._profiles[session_id] = profile
        return profile

    def update_comparison_areas(self, session_id: str, areas: list[str]) -> ProfileSnapshot:
        profile = self.require(session_id)
        profile.comparison_areas = [AREA_FIXTURES.get(a, TargetArea(area_id=a, area_name=a)) for a in areas[:5]]
        profile.updated_at = now_iso()
        with self._lock:
            self._profiles[session_id] = profile
        return profile

    def save_summary(self, session_id: str, summary: str) -> ProfileSnapshot:
        profile = self.require(session_id)
        profile.conversation_summary = summary[:800]
        profile.updated_at = now_iso()
        with self._lock:
            self._profiles[session_id] = profile
        return profile

    def save_last_response_refs(self, session_id: str, refs: dict) -> ProfileSnapshot:
        profile = self.require(session_id)
        profile.last_response_refs = refs
        profile.updated_at = now_iso()
        with self._lock:
            self._profiles[session_id] = profile
        return profile

    def delete_session(self, session_id: str) -> bool:
        with self._lock:
            return self._profiles.pop(session_id, None) is not None


store = ProfileStore()
