import type { DataQuality, DisplayRefs, MessageType, MetricCard, NextAction, SourceItem, WeatherCardData } from './api';
import type { ProfileSnapshot } from './profile';

export type ChatRequest = {
  session_id: string;
  message: string;
  debug?: boolean;
  client_context?: {
    active_area_id?: string | null;
    active_view?: string;
  };
};

export type TraceSummaryItem = {
  step: string;
  service: string;
  status: string;
  latency_ms: number;
  mcp?: string;
};

export type ChatDebug = {
  trace_summary: TraceSummaryItem[];
};

export type ChatResponseData = {
  message_type: MessageType;
  answer: string;
  next_action: NextAction;
  profile_snapshot: ProfileSnapshot;
  missing_slots?: string[];
  cards: Array<MetricCard | WeatherCardData>;
  display_refs: DisplayRefs;
  sources: SourceItem[];
  data_quality: DataQuality;
  debug: ChatDebug | null;
};

export type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  message_type: MessageType;
  content: string;
  created_at: string;
  cards: Array<MetricCard | WeatherCardData>;
  sources: SourceItem[];
};
