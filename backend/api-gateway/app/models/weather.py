from pydantic import BaseModel
from app.models.area import AreaSummary
from app.models.common import DataQuality, SourceItem, WeatherPeriod


class WeatherPayload(BaseModel):
    mode: str
    target_time: str | None = None
    periods: list[WeatherPeriod]


class WeatherResponse(BaseModel):
    area: AreaSummary
    weather: WeatherPayload
    data_quality: DataQuality
    source: list[SourceItem]
    updated_at: str
    expires_at: str | None = None
