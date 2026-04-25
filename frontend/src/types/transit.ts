import type { DataQuality, SourceItem } from './api';

export type TransitRealtimeRequest = {
  session_id: string;
  origin: string;
  destination: string;
  mode: 'subway' | 'bus' | 'either';
};

export type TransitDeparture = {
  route_id: string;
  stop_name: string;
  departure_time: string;
  minutes_until_departure: number;
  delay_seconds?: number;
};

export type TransitRealtimeResponse = {
  mode: 'subway' | 'bus';
  origin_stop: string;
  destination: string;
  walking_to_stop_minutes: number;
  waiting_minutes: number;
  in_vehicle_minutes: number;
  total_minutes: number;
  recommended_leave_at: string;
  estimated_arrival_at: string;
  realtime_used: boolean;
  fallback_used: boolean;
  departures: TransitDeparture[];
  data_quality: DataQuality;
  source: SourceItem[];
};
