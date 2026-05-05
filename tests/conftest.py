"""Shared test fixtures.

Three reusable fixtures live here:
- `gateway_url` / `data_sync_url` — env-overridable base URLs for live e2e.
- `pg_engine` — a SQLAlchemy engine pointed at the docker postgres (read-only
   use across tests is safe because we work in committed DB state).
- `isolated_schema` — creates a fresh PG schema with the project's DDL applied
   from db/init/002_schema.sql, returns an engine bound to that schema, and
   drops it on teardown. Use this for derivation-SQL correctness tests so
   fixtures are deterministic and don't pollute public.

`add_service_to_path()` is a helper for importing a single service's `app`
package without polluting later imports — used by unit tests that exercise
service-internal helpers (orchestrator-agent, data-sync-service, etc.).
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

REPO_ROOT = Path(__file__).resolve().parents[1]
SHARED_PATH = REPO_ROOT / "shared"
DDL_PATH = REPO_ROOT / "db" / "init" / "002_schema.sql"

PG_URL = os.environ.get(
    "TEST_PG_URL",
    "postgresql+psycopg://nyc_agent:nyc_agent_password@localhost:5432/nyc_agent",
)


@pytest.fixture(scope="session")
def gateway_url() -> str:
    return os.environ.get("GATEWAY_URL", "http://localhost:8000").rstrip("/")


@pytest.fixture(scope="session")
def data_sync_url() -> str:
    return os.environ.get("DATA_SYNC_URL", "http://localhost:8030").rstrip("/")


@pytest.fixture(scope="session")
def pg_url() -> str:
    return PG_URL


@pytest.fixture(scope="session")
def pg_engine(pg_url: str) -> Engine:
    """Read-only-friendly engine on the public schema."""
    return create_engine(pg_url, pool_pre_ping=True, future=True)


@pytest.fixture()
def isolated_schema(pg_url: str) -> Iterator[Engine]:
    """Create an ephemeral schema, apply DDL, yield engine, drop."""
    schema = f"test_{uuid.uuid4().hex[:10]}"
    admin = create_engine(pg_url, future=True, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        engine = create_engine(
            pg_url,
            future=True,
            connect_args={"options": f"-csearch_path={schema},public"},
        )
        # Apply just the table DDL we need; skip CREATE EXTENSION (postgis is
        # already installed cluster-wide) and view definitions that reference
        # tables we don't seed.
        ddl = DDL_PATH.read_text()
        # Strip the CREATE EXTENSION line — superuser-only and already done.
        ddl = "\n".join(
            line for line in ddl.splitlines()
            if not line.strip().startswith("CREATE EXTENSION")
        )
        with engine.begin() as conn:
            conn.execute(text(ddl))
        yield engine
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))


_SERVICES_DIR = REPO_ROOT / "services"
_GATEWAY_DIR = REPO_ROOT / "backend" / "api-gateway"


def _purge_app_namespace() -> None:
    for mod in list(sys.modules):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]


def _all_app_roots() -> list[str]:
    """Every directory whose `app/` package could shadow another's."""
    roots = [str(_GATEWAY_DIR)]
    for child in _SERVICES_DIR.iterdir():
        if (child / "app").is_dir():
            roots.append(str(child))
    return roots


def _swap_to(target: Path) -> None:
    """Make `target` the only `app/` package on sys.path. Idempotent."""
    _purge_app_namespace()
    for root in _all_app_roots():
        if root in sys.path and root != str(target):
            sys.path.remove(root)
    if str(target) not in sys.path:
        sys.path.insert(0, str(target))
    if str(SHARED_PATH) not in sys.path:
        sys.path.insert(0, str(SHARED_PATH))


def add_service_to_path(service_name: str) -> None:
    """Make `import app.foo` resolve to services/<name>/app/foo, and ensure
    no other service's `app/` shadows it. Test modules call this from a
    fixture so cross-file ordering can't corrupt the import path."""
    _swap_to(_SERVICES_DIR / service_name)


def add_gateway_to_path() -> None:
    """Like `add_service_to_path`, but binds `app.*` to the gateway."""
    _swap_to(_GATEWAY_DIR)
