import logging

from fastapi import FastAPI

from app.api import routes_health, routes_sync

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)

app = FastAPI(title="NYC Agent Data Sync Service", version="0.1.0")

app.include_router(routes_health.router, tags=["health"])
app.include_router(routes_sync.router, tags=["sync"])
