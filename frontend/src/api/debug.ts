import { apiRequest } from './client';
import type { ApiEnvelope } from '../types/api';
import type { TraceDebugResponse } from '../types/debug';

export async function getTraceDebug(traceId: string): Promise<ApiEnvelope<TraceDebugResponse>> {
  return apiRequest<TraceDebugResponse>(`/debug/traces/${traceId}`);
}
