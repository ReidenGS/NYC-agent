import { apiRequest } from './client';
import type { ApiEnvelope } from '../types/api';
import type { AreaMetricsResponse } from '../types/area';
import type { MapLayersResponse } from '../types/map';

export async function getAreaMetrics(areaId: string, sessionId: string): Promise<ApiEnvelope<AreaMetricsResponse>> {
  return apiRequest<AreaMetricsResponse>(`/areas/${areaId}/metrics?session_id=${encodeURIComponent(sessionId)}`);
}

export async function getMapLayers(areaId: string, sessionId: string): Promise<ApiEnvelope<MapLayersResponse>> {
  return apiRequest<MapLayersResponse>(`/areas/${areaId}/map-layers?session_id=${encodeURIComponent(sessionId)}`);
}
