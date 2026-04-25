from pydantic import BaseModel, Field
from app.models.common import DataQuality, DisplayRefs, MetricCard, MessageType, NextAction, SourceItem, WeatherCardData
from app.models.profile import ProfileSnapshot


class ChatRequest(BaseModel):
    session_id: str
    message: str
    debug: bool = False
    client_context: dict | None = None


class TraceSummaryItem(BaseModel):
    step: str
    service: str
    status: str
    latency_ms: int
    mcp: str | None = None


class ChatDebug(BaseModel):
    trace_summary: list[TraceSummaryItem]


class ChatResponseData(BaseModel):
    message_type: MessageType
    answer: str
    next_action: NextAction
    profile_snapshot: ProfileSnapshot
    missing_slots: list[str] = Field(default_factory=list)
    cards: list[MetricCard | WeatherCardData] = Field(default_factory=list)
    display_refs: DisplayRefs = Field(default_factory=DisplayRefs)
    sources: list[SourceItem] = Field(default_factory=list)
    data_quality: DataQuality = 'unknown'
    debug: ChatDebug | None = None
