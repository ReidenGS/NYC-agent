---
name: nyc-nl-to-sql
description: Convert NYC Agent structured housing or neighborhood tasks into safe read-only SQL plans. Use only after orchestrator has already produced domain, task_type, slots, and domain_user_query. Do not use for transit, weather, profile/session writes, raw intent detection, or final user-facing answers.
---

# NYC NL-to-SQL

Use this skill only for SQL-generation tasks that have already been structured by `orchestrator-agent`.

Do not use this skill for:

- `transit.*`
- `weather.*`
- `profile.*`
- raw user intent detection
- final user-facing natural language answers
- direct database access

## Phase 1.1 Loading Rule

Always load the common references:

- `references/common-sql-rules.md`
- `references/common-output-contract.md`
- `references/common-area-contract.md`

Then load only the intent reference and table references selected by code for the current `task_type`.

Do not include references for unrelated task types or unrelated tables.

The LLM must choose one `mcp_tool` per SQL query from the injected MCP SQL Tool Catalog.
Do not invent MCP tools, bypass MCP validation, or write final user-facing answers.

## Output

Return strict JSON only. The SQL plan must use the project SQL plan shape:

- `status`
- `neighborhood_result_type`
- `area_id`
- `area_name`
- `queries`
- `missing_slots`
- `clarification`
- `unsupported_reason`
- `missing_or_unavailable_fields`
- `suggested_alternative`
- `default_applied`
- `reason_summary`
