import { apiRequest, USE_MOCK_API } from './client';
import { envelope, mockAreaMetrics, mockMapLayers } from '../mocks/data';
import type { ApiEnvelope } from '../types/api';
import type { AreaMetricsResponse } from '../types/area';
import type { MapLayersResponse } from '../types/map';

export async function getAreaMetrics(areaId: string, sessionId: string): Promise<ApiEnvelope<AreaMetricsResponse>> {
  if (USE_MOCK_API) return envelope(mockAreaMetrics, sessionId);
  return apiRequest<AreaMetricsResponse>(`/areas/${areaId}/metrics?session_id=${encodeURIComponent(sessionId)}`);
}

export async function getMapLayers(areaId: string, sessionId: string): Promise<ApiEnvelope<MapLayersResponse>> {
  if (USE_MOCK_API) return envelope(mockMapLayers, sessionId);
  return apiRequest<MapLayersResponse>(`/areas/${areaId}/map-layers?session_id=${encodeURIComponent(sessionId)}`);
}
