from pydantic import BaseModel
from app.models.chat import TraceSummaryItem


class TraceDebugResponse(BaseModel):
    trace_id: str
    trace_summary: list[TraceSummaryItem]
