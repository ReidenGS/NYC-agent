from pydantic import BaseModel, Field


class Budget(BaseModel):
    min: float | None = None
    max: float | None = None
    currency: str = 'USD'


class DecisionWeights(BaseModel):
    safety: float = 0.35
    commute: float = 0.25
    rent: float = 0.20
    convenience: float = 0.10
    entertainment: float = 0.10


class TargetArea(BaseModel):
    area_id: str
    area_name: str
    borough: str | None = None


class ProfileSnapshot(BaseModel):
    session_id: str
    target_area: TargetArea | None = None
    target_area_id: str | None = None
    budget: Budget | None = None
    target_destination: str | None = None
    max_commute_minutes: int | None = None
    preferences: list[str] = Field(default_factory=list)
    weights: DecisionWeights = Field(default_factory=DecisionWeights)
    missing_required_fields: list[str] = Field(default_factory=list)
    conversation_summary: str = ''
    updated_at: str


class SessionCreateRequest(BaseModel):
    client_timezone: str | None = None
    client_locale: str | None = None


class SessionCreateResponse(BaseModel):
    session_id: str
    profile_snapshot: ProfileSnapshot


class ProfilePatchRequest(BaseModel):
    target_area_id: str | None = None
    budget: Budget | None = None
    target_destination: str | None = None
    max_commute_minutes: int | None = None
    weights: DecisionWeights | None = None
    preferences: list[str] | None = None
