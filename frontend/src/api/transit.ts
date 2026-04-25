import { apiRequest, USE_MOCK_API } from './client';
import { envelope, mockTransit } from '../mocks/data';
import type { ApiEnvelope } from '../types/api';
import type { TransitRealtimeRequest, TransitRealtimeResponse } from '../types/transit';

export async function getRealtimeTransit(request: TransitRealtimeRequest): Promise<ApiEnvelope<TransitRealtimeResponse>> {
  if (USE_MOCK_API) return envelope(mockTransit, request.session_id);
  return apiRequest<TransitRealtimeResponse>('/transit/realtime', {
    method: 'POST',
    body: JSON.stringify(request)
  });
}
