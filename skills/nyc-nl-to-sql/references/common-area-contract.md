# Common Area Contract

The area has already been resolved by `orchestrator-agent`.

Use:

- `slots.area_id.value` as the canonical `area_id`.
- `slots.area_name.value` only for display.

Do not:

- perform Area RAG
- infer a different area
- use the raw user query to look up an area
- use `area_name` as the primary SQL filter when `area_id` is present

If `area_id` is missing, return:

```json
{
  "status": "clarification_required",
  "missing_slots": ["target_area"],
  "clarification": "请先告诉我你想查询的区域。",
  "queries": []
}
```

