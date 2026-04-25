export type DataQuality = 'realtime' | 'reference' | 'estimated' | 'benchmark' | 'cached' | 'no_data' | 'unknown';

export type MessageType = 'answer' | 'follow_up' | 'confirmation' | 'no_data' | 'unsupported' | 'error';

export type NextAction =
  | 'ask_follow_up'
  | 'confirm_slots'
  | 'update_profile'
  | 'call_agent'
  | 'call_mcp'
  | 'respond_final'
  | 'run_async_task'
  | 'fallback'
  | 'error';

export type ApiError = {
  code: string;
  message: string;
  retryable: boolean;
  details: Record<string, unknown>;
};

export type ApiEnvelope<T> = {
  success: boolean;
  trace_id: string;
  session_id?: string | null;
  data: T | null;
  error: ApiError | null;
};

export type SourceItem = {
  name: string;
  type?: string;
  url?: string;
  updated_at?: string;
  timestamp?: string;
};

export type MetricItem = {
  label: string;
  value: number | string;
  unit?: string;
};

export type MetricCard = {
  card_type: 'metric';
  title: string;
  subtitle?: string;
  score_label?: string;
  metrics: MetricItem[];
  data_quality?: DataQuality;
  source?: SourceItem[];
};

export type WeatherCardData = {
  card_type: 'weather';
  title: string;
  subtitle?: string;
  periods: Array<{
    start_time: string;
    end_time: string;
    temperature: number;
    temperature_unit: string;
    precipitation_probability: number | null;
    wind_speed: string;
    wind_direction: string;
    short_forecast: string;
    is_daytime: boolean;
  }>;
  data_quality: DataQuality;
  source: SourceItem[];
};

export type DisplayRefs = {
  map_layer_ids: string[];
  display_result_ids: string[];
};
