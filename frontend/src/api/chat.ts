import { apiRequest, DEBUG_MODE, USE_MOCK_API } from './client';
import { mockChat } from '../mocks/data';
import type { ApiEnvelope } from '../types/api';
import type { ChatRequest, ChatResponseData } from '../types/chat';

export async function sendChat(request: ChatRequest): Promise<ApiEnvelope<ChatResponseData>> {
  if (USE_MOCK_API) return mockChat(request.message);

  return apiRequest<ChatResponseData>('/chat', {
    method: 'POST',
    body: JSON.stringify({ ...request, debug: request.debug ?? DEBUG_MODE })
  });
}
