from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from app.db.session import db_session

router = APIRouter()


def _jsonable(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _row_dict(row: Any) -> dict[str, Any]:
    return {key: _jsonable(value) for key, value in dict(row).items()}


@router.get("/areas/{area_id}/metrics")
def area_metrics(area_id: str) -> dict[str, Any]:
    sql = text(
        """
        SELECT
            a.area_id,
            a.area_name,
            a.borough,
            ST_Y(ST_Centroid(a.geom))::float AS latitude,
            ST_X(ST_Centroid(a.geom))::float AS longitude,
            m.metric_date,
            m.crime_count_30d,
            m.crime_index_100,
            m.entertainment_poi_count,
            m.convenience_facility_count,
            m.transit_station_count,
            m.complaint_noise_30d,
            m.rent_index_value,
            m.source_snapshot,
            COALESCE(m.updated_at, a.updated_at) AS updated_at
        FROM app_area_dimension a
        LEFT JOIN v_area_metrics_latest m ON m.area_id = a.area_id
        WHERE a.area_id = :area_id
        """
    )
    with db_session() as session:
        row = session.execute(sql, {"area_id": area_id}).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"area_id not found: {area_id}")
    data = _row_dict(row)
    for key in (
        "crime_count_30d",
        "crime_index_100",
        "entertainment_poi_count",
        "convenience_facility_count",
        "transit_station_count",
        "complaint_noise_30d",
        "rent_index_value",
    ):
        data[key] = data.get(key) or 0
    data["source_snapshot"] = data.get("source_snapshot") or {}
    return data


@router.get("/areas/{area_id}/map-layers")
def area_map_layers(
    area_id: str,
    layer_types: str = Query("choropleth,marker"),
    metric_names: str = Query("crime_index,entertainment,convenience"),
) -> dict[str, Any]:
    layer_type_list = [item.strip() for item in layer_types.split(",") if item.strip()]
    metric_name_list = [item.strip() for item in metric_names.split(",") if item.strip()]
    sql = text(
        """
        SELECT layer_id, layer_type, metric_name, geojson, style_hint,
               source_snapshot, updated_at, expires_at
        FROM app_map_layer_cache
        WHERE area_id = :area_id
          AND (:layer_types_empty OR layer_type = ANY(:layer_types))
          AND (:metric_names_empty OR metric_name = ANY(:metric_names))
        ORDER BY metric_date DESC, layer_type, metric_name
        """
    )
    with db_session() as session:
        area_exists = session.execute(
            text("SELECT 1 FROM app_area_dimension WHERE area_id = :area_id"),
            {"area_id": area_id},
        ).first()
        if area_exists is None:
            raise HTTPException(status_code=404, detail=f"area_id not found: {area_id}")
        rows = session.execute(
            sql,
            {
                "area_id": area_id,
                "layer_types": layer_type_list,
                "layer_types_empty": not layer_type_list,
                "metric_names": metric_name_list,
                "metric_names_empty": not metric_name_list,
            },
        ).mappings().all()

    layers = []
    for row in rows:
        item = _row_dict(row)
        source_snapshot = item.pop("source_snapshot", None) or {}
        item["data_quality"] = source_snapshot.get("data_quality") or "reference"
        layers.append(item)
    return {"area_id": area_id, "layers": layers}
