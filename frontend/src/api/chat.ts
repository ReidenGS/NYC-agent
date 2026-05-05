import { apiRequest, DEBUG_MODE } from './client';
import type { ApiEnvelope } from '../types/api';
import type { ChatRequest, ChatResponseData } from '../types/chat';

export async function sendChat(request: ChatRequest): Promise<ApiEnvelope<ChatResponseData>> {
  return apiRequest<ChatResponseData>('/chat', {
    method: 'POST',
    body: JSON.stringify({ ...request, debug: request.debug ?? DEBUG_MODE })
  });
}
