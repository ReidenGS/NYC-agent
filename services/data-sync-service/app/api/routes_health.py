from fastapi import APIRouter
from sqlalchemy import text

from app.db.session import engine

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/ready")
def ready() -> dict:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            postgis = conn.execute(text("SELECT PostGIS_Version()")).scalar()
        return {"status": "ok", "postgis": postgis}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
