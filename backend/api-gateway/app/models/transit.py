from typing import Literal
from pydantic import BaseModel
from app.models.common import DataQuality, SourceItem


class TransitRealtimeRequest(BaseModel):
    session_id: str
    origin: str
    destination: str
    mode: Literal['subway', 'bus', 'either'] = 'either'


class TransitDeparture(BaseModel):
    route_id: str
    stop_name: str
    departure_time: str
    minutes_until_departure: int
    delay_seconds: int | None = None


class TransitRealtimeResponse(BaseModel):
    mode: Literal['subway', 'bus']
    origin_stop: str
    destination: str
    walking_to_stop_minutes: int
    waiting_minutes: int
    in_vehicle_minutes: int
    total_minutes: int
    recommended_leave_at: str
    estimated_arrival_at: str
    realtime_used: bool
    fallback_used: bool
    departures: list[TransitDeparture]
    data_quality: DataQuality
    source: list[SourceItem]
