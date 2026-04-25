import type { MetricCard, SourceItem } from './api';

export type AreaSummary = {
  area_id: string;
  area_name: string;
  borough: string;
  latitude?: number;
  longitude?: number;
};

export type AreaMetrics = {
  crime_count_30d: number;
  crime_index_100: number;
  entertainment_poi_count: number;
  convenience_facility_count: number;
  transit_station_count: number;
  complaint_noise_30d: number;
  rent_index_value: number;
};

export type AreaMetricsResponse = {
  area: AreaSummary;
  metrics: AreaMetrics;
  metric_cards: MetricCard[];
  source_snapshot: Record<string, unknown>;
  updated_at: string;
};

export type AreaOption = AreaSummary & {
  median_rent: number;
};
