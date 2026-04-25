import { apiRequest, USE_MOCK_API } from './client';
import { mockCreateSession } from '../mocks/data';
import type { ApiEnvelope } from '../types/api';
import type { SessionCreateResponse } from '../types/profile';

export async function createSession(): Promise<ApiEnvelope<SessionCreateResponse>> {
  if (USE_MOCK_API) return mockCreateSession();

  return apiRequest<SessionCreateResponse>('/sessions', {
    method: 'POST',
    body: JSON.stringify({ client_timezone: 'America/New_York', client_locale: 'zh-CN' })
  });
}
