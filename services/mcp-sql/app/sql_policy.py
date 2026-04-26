from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


DOMAIN_TABLES: dict[str, set[str]] = {
    "housing": {
        "app_area_dimension",
        "app_area_rental_market_daily",
        "app_area_rental_listing_snapshot",
        "app_area_rent_benchmark_monthly",
        "v_area_metrics_latest",
    },
    "safety": {
        "app_area_dimension",
        "app_crime_incident_snapshot",
        "v_area_metrics_latest",
    },
    "amenity": {
        "app_area_dimension",
        "app_area_convenience_category_daily",
        "app_map_poi_snapshot",
        "v_area_metrics_latest",
    },
    "entertainment": {
        "app_area_dimension",
        "app_area_entertainment_category_daily",
        "app_map_poi_snapshot",
        "v_area_metrics_latest",
    },
}

SENSITIVE_TABLES = {
    "app_session_profile",
    "app_session_recommendation",
    "app_a2a_trace_log",
    "app_data_sync_job_log",
}

DENY_KEYWORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|copy|grant|revoke|vacuum|analyze|call|do|execute|merge)\b",
    re.IGNORECASE,
)
TABLE_REF_RE = re.compile(r"\b(?:from|join)\s+([a-zA-Z_][\w.]*)(?:\s+|$)", re.IGNORECASE)
LIMIT_RE = re.compile(r"\blimit\s+(\d+)\b", re.IGNORECASE)
PARAM_RE = re.compile(r"(?<!:):([a-zA-Z_]\w*)")


@dataclass
class SqlValidationResult:
    ok: bool
    source_tables: list[str] = field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = True


def extract_table_names(sql: str) -> list[str]:
    tables: list[str] = []
    for match in TABLE_REF_RE.finditer(sql):
        table = match.group(1).split(".")[-1].strip('"').lower()
        if table not in tables:
            tables.append(table)
    return tables


def validate_sql(sql: str, params: dict[str, Any], domain: str, max_rows: int = 50) -> SqlValidationResult:
    original = sql
    sql = sql.strip()
    normalized = re.sub(r"\s+", " ", sql).strip()
    domain = domain.lower().strip()
    allowed_tables = DOMAIN_TABLES.get(domain)
    if not allowed_tables:
        return SqlValidationResult(False, error_code="UNSUPPORTED_DOMAIN", error_message=f"unsupported SQL domain: {domain}", retryable=False)

    if not normalized:
        return SqlValidationResult(False, error_code="SQL_EMPTY", error_message="SQL is empty.")
    if not re.match(r"^(select|with)\b", normalized, re.IGNORECASE):
        return SqlValidationResult(False, error_code="SQL_NOT_READONLY", error_message="Only SELECT/WITH readonly SQL is allowed.")
    if ";" in normalized.rstrip(";"):
        return SqlValidationResult(False, error_code="SQL_MULTI_STATEMENT", error_message="Multiple SQL statements are not allowed.")
    if normalized.count(";") > 1:
        return SqlValidationResult(False, error_code="SQL_MULTI_STATEMENT", error_message="Multiple SQL statements are not allowed.")
    if "--" in original or "/*" in original or "*/" in original:
        return SqlValidationResult(False, error_code="SQL_COMMENT_NOT_ALLOWED", error_message="SQL comments are not allowed.")
    if DENY_KEYWORDS.search(normalized):
        return SqlValidationResult(False, error_code="SQL_FORBIDDEN_KEYWORD", error_message="DDL/DML or unsafe SQL keyword detected.")
    if re.search(r"\bselect\s+\*", normalized, re.IGNORECASE) or re.search(r",\s*\*", normalized):
        return SqlValidationResult(False, error_code="SQL_SELECT_STAR", error_message="SELECT * is not allowed.")

    limit_match = LIMIT_RE.search(normalized)
    if not limit_match:
        return SqlValidationResult(False, error_code="SQL_LIMIT_REQUIRED", error_message="Every query must include LIMIT.")
    limit_value = int(limit_match.group(1))
    if limit_value > max_rows:
        return SqlValidationResult(False, error_code="SQL_LIMIT_TOO_HIGH", error_message=f"LIMIT must be <= {max_rows}.")

    source_tables = extract_table_names(normalized)
    if not source_tables:
        return SqlValidationResult(False, error_code="SQL_TABLE_REQUIRED", error_message="SQL must reference at least one table or view.")
    forbidden_sensitive = sorted(set(source_tables) & SENSITIVE_TABLES)
    if forbidden_sensitive:
        return SqlValidationResult(False, source_tables, "SQL_SENSITIVE_TABLE", f"Sensitive tables are not allowed: {', '.join(forbidden_sensitive)}.", retryable=False)
    forbidden = sorted(set(source_tables) - allowed_tables)
    if forbidden:
        return SqlValidationResult(False, source_tables, "SQL_TABLE_NOT_ALLOWED", f"Tables not allowed for domain {domain}: {', '.join(forbidden)}.")

    required_params = set(PARAM_RE.findall(normalized))
    missing_params = sorted(required_params - set(params.keys()))
    if missing_params:
        return SqlValidationResult(False, source_tables, "SQL_PARAM_MISSING", f"Missing SQL params: {', '.join(missing_params)}.")

    return SqlValidationResult(True, source_tables=source_tables)
