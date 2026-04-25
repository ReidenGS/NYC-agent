from typing import Generic, Literal, TypeVar
from pydantic import BaseModel, Field

DataQuality = Literal['realtime', 'reference', 'estimated', 'benchmark', 'cached', 'no_data', 'unknown']
MessageType = Literal['answer', 'follow_up', 'confirmation', 'no_data', 'unsupported', 'error']
NextAction = Literal[
    'ask_follow_up', 'confirm_slots', 'update_profile', 'call_agent', 'call_mcp',
    'respond_final', 'run_async_task', 'fallback', 'error'
]

T = TypeVar('T')


class ApiError(BaseModel):
    code: str
    message: str
    retryable: bool
    details: dict = Field(default_factory=dict)


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


class MetricItem(BaseModel):
    label: str
    value: int | float | str
    unit: str | None = None


class MetricCard(BaseModel):
    card_type: Literal['metric'] = 'metric'
    title: str
    subtitle: str | None = None
    score_label: str | None = None
    metrics: list[MetricItem]
    data_quality: DataQuality = 'reference'
    source: list[SourceItem] = Field(default_factory=list)


class WeatherPeriod(BaseModel):
    start_time: str
    end_time: str
    temperature: int | float
    temperature_unit: str
    precipitation_probability: int | None = None
    wind_speed: str
    wind_direction: str
    short_forecast: str
    detailed_forecast: str | None = None
    is_daytime: bool


class WeatherCardData(BaseModel):
    card_type: Literal['weather'] = 'weather'
    title: str
    subtitle: str | None = None
    periods: list[WeatherPeriod]
    data_quality: DataQuality
    source: list[SourceItem]


class DisplayRefs(BaseModel):
    map_layer_ids: list[str] = Field(default_factory=list)
    display_result_ids: list[str] = Field(default_factory=list)
