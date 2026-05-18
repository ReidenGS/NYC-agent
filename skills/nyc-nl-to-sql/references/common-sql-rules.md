# Common SQL Rules

Generate a strict JSON SQL plan only. Do not output Markdown, explanations, final user-facing answers, or actual tool call messages.

Rules:

- Return `SELECT` only.
- Never return `SELECT *`.
- Every query must include `LIMIT`.
- Detail / point queries must use `LIMIT <= 20`.
- Use named params for user-provided values.
- Do not access profile, session, debug, sync, checkpoint, or internal tables.
- At most 3 queries.
- `purpose` must be one of `analysis`, `detail`, or `fallback`.
- Every query must include exactly one `mcp_tool` from the injected MCP SQL Tool Catalog.
- Do not invent MCP tools.
- Do not bypass MCP SQL validation.
- If required slots are missing, return `clarification_required`.
- If the requested data is outside the injected schema, return `unsupported_data_request`.
