import { apiRequest } from './client';
import type { ApiEnvelope } from '../types/api';
import type { TransitRealtimeRequest, TransitRealtimeResponse } from '../types/transit';

export async function getRealtimeTransit(request: TransitRealtimeRequest): Promise<ApiEnvelope<TransitRealtimeResponse>> {
  return apiRequest<TransitRealtimeResponse>('/transit/realtime', {
    method: 'POST',
    body: JSON.stringify(request)
  });
}
