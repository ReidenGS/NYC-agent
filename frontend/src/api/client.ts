import type { ApiEnvelope } from '../types/api';

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';
export const USE_MOCK_API = import.meta.env.VITE_USE_MOCK_API !== 'false';
export const DEBUG_MODE = import.meta.env.VITE_DEBUG_MODE === 'true';
export const MAPTILER_API_KEY = import.meta.env.VITE_MAPTILER_API_KEY ?? '';

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<ApiEnvelope<T>> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {})
    }
  });

  const payload = (await response.json()) as ApiEnvelope<T>;

  if (!response.ok || !payload.success) {
    throw payload.error ?? {
      code: 'HTTP_ERROR',
      message: `Request failed with status ${response.status}`,
      retryable: response.status >= 500,
      details: {}
    };
  }

  return payload;
}
