from pydantic import BaseModel, Field
from app.models.common import DataQuality, MetricCard


class AreaSummary(BaseModel):
    area_id: str
    area_name: str
    borough: str
    latitude: float | None = None
    longitude: float | None = None


class AreaMetrics(BaseModel):
    crime_count_30d: int
    crime_index_100: float
    entertainment_poi_count: int
    convenience_facility_count: int
    transit_station_count: int
    complaint_noise_30d: int
    rent_index_value: float


class AreaMetricsResponse(BaseModel):
    area: AreaSummary
    metrics: AreaMetrics
    metric_cards: list[MetricCard]
    source_snapshot: dict = Field(default_factory=dict)
    updated_at: str


class GeoJsonGeometry(BaseModel):
    type: str
    coordinates: object


class GeoJsonFeature(BaseModel):
    type: str = 'Feature'
    geometry: GeoJsonGeometry
    properties: dict = Field(default_factory=dict)


class GeoJsonFeatureCollection(BaseModel):
    type: str = 'FeatureCollection'
    features: list[GeoJsonFeature]


class MapLayer(BaseModel):
    layer_id: str
    layer_type: str
    metric_name: str
    geojson: GeoJsonFeatureCollection
    style_hint: dict = Field(default_factory=dict)
    data_quality: DataQuality
    updated_at: str
    expires_at: str | None = None


class MapLayersResponse(BaseModel):
    area_id: str
    layers: list[MapLayer]
