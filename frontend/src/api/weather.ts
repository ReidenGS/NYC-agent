import { apiRequest } from './client';
import type { ApiEnvelope } from '../types/api';
import type { WeatherResponse } from '../types/weather';

export async function getAreaWeather(areaId: string, sessionId: string): Promise<ApiEnvelope<WeatherResponse>> {
  return apiRequest<WeatherResponse>(`/areas/${areaId}/weather?session_id=${encodeURIComponent(sessionId)}&hours=6`);
}
