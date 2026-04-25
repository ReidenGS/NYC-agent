import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import scheduler as scheduler_mod
from app.api import routes_health, routes_sync

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Reuse the same ThreadPool as manual /sync/run/{job_name} so scheduled
    # and manual dispatches serialize through one worker. routes_sync._executor
    # is created at module import time.
    scheduler_mod.start(routes_sync._executor)
    try:
        yield
    finally:
        scheduler_mod.shutdown()


app = FastAPI(
    title="NYC Agent Data Sync Service",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(routes_health.router, tags=["health"])
app.include_router(routes_sync.router, tags=["sync"])
