# Common Output Contract

Return one JSON object with this shape:

```json
{
  "status": "sql_ready",
  "neighborhood_result_type": "amenity_breakdown",
  "area_id": "QN0101",
  "area_name": "Astoria",
  "queries": [
    {
      "mcp_tool": "task_specific_mcp_tool",
      "target_table": "task_specific_allowed_table",
      "domain": "task_specific_domain",
      "purpose": "analysis",
      "execute_when": "always",
      "expected_result": "task_specific_expected_result",
      "sql": "SELECT ... WHERE area_id = :area_id LIMIT 20",
      "params": {"area_id": "QN0101"}
    }
  ],
  "missing_slots": [],
  "clarification": "",
  "unsupported_reason": "",
  "missing_or_unavailable_fields": [],
  "suggested_alternative": "",
  "default_applied": [],
  "reason_summary": "Generated safe read-only SQL plan."
}
```

Allowed `status` values:

- `sql_ready`
- `clarification_required`
- `unsupported_data_request`

Every query must include:

- `mcp_tool`
- `target_table`
- `domain`
- `purpose`
- `execute_when`
- `expected_result`
- `sql`
- `params`

Allowed query domains:

- `amenity`
- `entertainment`
- `housing`
- `safety`
