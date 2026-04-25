import type { DataQuality, SourceItem } from './api';
import type { AreaSummary } from './area';

export type WeatherPeriod = {
  start_time: string;
  end_time: string;
  temperature: number;
  temperature_unit: string;
  precipitation_probability: number | null;
  wind_speed: string;
  wind_direction: string;
  short_forecast: string;
  detailed_forecast?: string;
  is_daytime: boolean;
};

export type WeatherResponse = {
  area: AreaSummary;
  weather: {
    mode: 'hourly_summary' | 'target_time';
    target_time: string | null;
    periods: WeatherPeriod[];
  };
  data_quality: DataQuality;
  source: SourceItem[];
  updated_at: string;
  expires_at: string | null;
};
