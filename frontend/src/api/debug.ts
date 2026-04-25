import { apiRequest, USE_MOCK_API } from './client';
import { envelope } from '../mocks/data';
import type { ApiEnvelope } from '../types/api';
import type { TraceDebugResponse } from '../types/debug';

export async function getTraceDebug(traceId: string): Promise<ApiEnvelope<TraceDebugResponse>> {
  if (USE_MOCK_API) {
    return envelope({
      trace_id: traceId,
      trace_summary: [
        { step: 'orchestrator.intent_detected', service: 'orchestrator-agent', status: 'success', latency_ms: 120 },
        { step: 'mcp.map_layers', service: 'neighborhood-agent', mcp: 'mcp-safety', status: 'success', latency_ms: 260 }
      ]
    });
  }
  return apiRequest<TraceDebugResponse>(`/debug/traces/${traceId}`);
}
