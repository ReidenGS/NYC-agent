import { apiRequest, USE_MOCK_API } from './client';
import { envelope, mockWeather } from '../mocks/data';
import type { ApiEnvelope } from '../types/api';
import type { WeatherResponse } from '../types/weather';

export async function getAreaWeather(areaId: string, sessionId: string): Promise<ApiEnvelope<WeatherResponse>> {
  if (USE_MOCK_API) return envelope(mockWeather, sessionId);
  return apiRequest<WeatherResponse>(`/areas/${areaId}/weather?session_id=${encodeURIComponent(sessionId)}&hours=6`);
}
