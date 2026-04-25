from __future__ import annotations

from threading import Lock
from uuid import uuid4

from app.models.profile import Budget, DecisionWeights, ProfilePatchRequest, ProfileSnapshot, TargetArea
from app.services.mock_data import get_area, now_iso


class SessionStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._profiles: dict[str, ProfileSnapshot] = {}

    def create(self) -> ProfileSnapshot:
        session_id = f'sess_{uuid4().hex[:16]}'
        area = get_area('QN0101')
        profile = ProfileSnapshot(
            session_id=session_id,
            target_area=TargetArea(area_id=area.area_id, area_name=area.area_name, borough=area.borough),
            target_area_id=area.area_id,
            budget=Budget(min=2500, max=3800),
            target_destination='NYU',
            max_commute_minutes=40,
            preferences=['安静', '少换乘'],
            weights=DecisionWeights(),
            missing_required_fields=[],
            conversation_summary='Demo session initialized with Astoria as the current target area.',
            updated_at=now_iso(),
        )
        with self._lock:
            self._profiles[session_id] = profile
        return profile

    def get(self, session_id: str) -> ProfileSnapshot | None:
        with self._lock:
            return self._profiles.get(session_id)

    def update_area(self, session_id: str, area_id: str) -> ProfileSnapshot:
        profile = self.require(session_id)
        area = get_area(area_id)
        profile.target_area = TargetArea(area_id=area.area_id, area_name=area.area_name, borough=area.borough)
        profile.target_area_id = area.area_id
        profile.missing_required_fields = []
        profile.updated_at = now_iso()
        with self._lock:
            self._profiles[session_id] = profile
        return profile

    def patch(self, session_id: str, patch: ProfilePatchRequest) -> ProfileSnapshot:
        profile = self.require(session_id)
        if patch.target_area_id:
            profile = self.update_area(session_id, patch.target_area_id)
        if patch.budget is not None:
            profile.budget = patch.budget
        if patch.target_destination is not None:
            profile.target_destination = patch.target_destination
        if patch.max_commute_minutes is not None:
            profile.max_commute_minutes = patch.max_commute_minutes
        if patch.weights is not None:
            profile.weights = patch.weights
        if patch.preferences is not None:
            profile.preferences = patch.preferences
        profile.updated_at = now_iso()
        with self._lock:
            self._profiles[session_id] = profile
        return profile

    def require(self, session_id: str) -> ProfileSnapshot:
        profile = self.get(session_id)
        if profile is None:
            raise KeyError(session_id)
        return profile


session_store = SessionStore()
