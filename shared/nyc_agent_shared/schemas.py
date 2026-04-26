from __future__ import annotations

from typing import Any, Generic, Literal, TypeVar
from pydantic import BaseModel, Field

T = TypeVar('T')

DataQuality = Literal['realtime', 'reference', 'estimated', 'benchmark', 'cached', 'no_data', 'unknown']


class ApiError(BaseModel):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class ApiEnvelope(BaseModel, Generic[T]):
    success: bool
    trace_id: str
    session_id: str | None = None
    data: T | None = None
    error: ApiError | None = None


class SourceItem(BaseModel):
    name: str
    type: str | None = None
    url: str | None = None
    updated_at: str | None = None
    timestamp: str | None = None


class Budget(BaseModel):
    min: float | None = None
    max: float | None = None
    currency: str = 'USD'


class DecisionWeights(BaseModel):
    safety: float = 0.30
    commute: float = 0.30
    rent: float = 0.20
    convenience: float = 0.10
    entertainment: float = 0.10

    def normalized(self) -> 'DecisionWeights':
        values = self.model_dump()
        total = sum(max(float(v), 0.0) for v in values.values())
        if total <= 0:
            return DecisionWeights()
        return DecisionWeights(**{k: round(max(float(v), 0.0) / total, 4) for k, v in values.items()})


class TargetArea(BaseModel):
    area_id: str
    area_name: str
    borough: str | None = None


class ProfileSnapshot(BaseModel):
    session_id: str
    target_area: TargetArea | None = None
    target_area_id: str | None = None
    comparison_areas: list[TargetArea] = Field(default_factory=list)
    budget: Budget | None = None
    target_destination: str | None = None
    max_commute_minutes: int | None = None
    preferences: list[str] = Field(default_factory=list)
    weights: DecisionWeights = Field(default_factory=DecisionWeights)
    missing_required_fields: list[str] = Field(default_factory=lambda: ['target_area'])
    conversation_summary: str = ''
    last_response_refs: dict[str, Any] = Field(default_factory=dict)
    updated_at: str


class A2ARequest(BaseModel):
    trace_id: str
    session_id: str | None = None
    source_agent: str
    target_agent: str
    task_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    debug: bool = False


class A2AResponse(BaseModel):
    trace_id: str
    session_id: str | None = None
    source_agent: str
    target_agent: str
    task_type: str
    status: Literal['success', 'no_data', 'unsupported_data_request', 'clarification_required', 'validation_failed', 'dependency_failed', 'error']
    payload: dict[str, Any] = Field(default_factory=dict)
    error: ApiError | None = None
