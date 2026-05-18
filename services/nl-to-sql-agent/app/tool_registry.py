from __future__ import annotations

from dataclasses import dataclass

from app.config import settings


@dataclass(frozen=True)
class McpSqlTool:
    tool_id: str
    server_name: str
    tool_name: str
    base_url: str
    description: str
    domains: tuple[str, ...]
    target_tables: tuple[str, ...]
    readable_tables: tuple[str, ...]


def _tools() -> dict[str, McpSqlTool]:
    return {
        "mcp-entertainment.execute_readonly_sql": McpSqlTool(
            tool_id="mcp-entertainment.execute_readonly_sql",
            server_name="mcp-entertainment",
            tool_name="execute_readonly_sql",
            base_url=settings.mcp_entertainment_url,
            description="Use for neighborhood entertainment category and entertainment POI SQL.",
            domains=("entertainment",),
            target_tables=("app_area_entertainment_category_daily", "app_map_poi_snapshot"),
            readable_tables=("app_area_dimension", "app_area_entertainment_category_daily", "app_map_poi_snapshot"),
        ),
        "mcp-amenity.execute_readonly_sql": McpSqlTool(
            tool_id="mcp-amenity.execute_readonly_sql",
            server_name="mcp-amenity",
            tool_name="execute_readonly_sql",
            base_url=settings.mcp_amenity_url,
            description="Use for neighborhood convenience/amenity category and convenience POI SQL.",
            domains=("amenity",),
            target_tables=("app_area_convenience_category_daily", "app_map_poi_snapshot"),
            readable_tables=("app_area_dimension", "app_area_convenience_category_daily", "app_map_poi_snapshot"),
        ),
        "mcp-safety.execute_readonly_sql": McpSqlTool(
            tool_id="mcp-safety.execute_readonly_sql",
            server_name="mcp-safety",
            tool_name="execute_readonly_sql",
            base_url=settings.mcp_safety_url,
            description="Use for neighborhood crime breakdown and area-level metric snapshot SQL.",
            domains=("safety",),
            target_tables=(
                "v_area_metrics_latest",
                "app_crime_incident_snapshot",
                "app_area_metrics_daily",
            ),
            readable_tables=(
                "app_area_dimension",
                "v_area_metrics_latest",
                "app_crime_incident_snapshot",
                "app_area_metrics_daily",
            ),
        ),
        "mcp-housing.execute_readonly_sql": McpSqlTool(
            tool_id="mcp-housing.execute_readonly_sql",
            server_name="mcp-housing",
            tool_name="execute_readonly_sql",
            base_url=settings.mcp_housing_url,
            description="Use for housing rent market, rent benchmark, and rental listing SQL.",
            domains=("housing",),
            target_tables=(
                "app_area_rental_market_daily",
                "app_area_rent_benchmark_monthly",
                "app_area_rental_listing_snapshot",
            ),
            readable_tables=(
                "app_area_dimension",
                "app_area_rental_market_daily",
                "app_area_rent_benchmark_monthly",
                "app_area_rental_listing_snapshot",
            ),
        ),
    }


def get_mcp_sql_tool(tool_id: str) -> McpSqlTool:
    try:
        return _tools()[tool_id]
    except KeyError as exc:
        raise ValueError(f"unsupported MCP SQL tool: {tool_id}") from exc


def list_mcp_sql_tools() -> dict[str, McpSqlTool]:
    return _tools()


def render_mcp_tool_catalog() -> str:
    lines = [
        "# MCP SQL Tool Catalog",
        "",
        "Every SQL query in `queries[]` must include exactly one `mcp_tool` from this catalog.",
        "Do not invent MCP tools. Do not use transit, weather, or profile MCP tools for SQL generation.",
        "",
    ]
    for tool in _tools().values():
        lines.extend(
            [
                f"## {tool.tool_id}",
                tool.description,
                f"- Allowed domains: {', '.join(tool.domains)}",
                f"- Allowed target_table values: {', '.join(tool.target_tables)}",
                f"- SQL may read these tables: {', '.join(tool.readable_tables)}",
                "",
            ]
        )
    return "\n".join(lines).strip()
