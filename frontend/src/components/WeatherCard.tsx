import { CloudSun } from 'lucide-react';
import { DashboardCard } from './DashboardCard';
import type { WeatherResponse } from '../types/weather';

type Props = {
  weather: WeatherResponse | null;
  isExpanded: boolean;
  onToggle: (id: string) => void;
};

export function WeatherCard({ weather, isExpanded, onToggle }: Props) {
  const first = weather?.weather.periods[0];

  return (
    <DashboardCard id="weather" title="天气" icon={CloudSun} variant="dark" isExpanded={isExpanded} onToggle={onToggle}>
      {first ? (
        <div className="weather-panel">
          <div className="weather-panel__hero">
            <div>
              <strong>{first.temperature}°{first.temperature_unit}</strong>
              <p>{first.short_forecast}</p>
            </div>
            <span>{weather.data_quality}</span>
          </div>
          <div className="weather-grid">
            <div>
              <span className="label">降水概率</span>
              <strong>{first.precipitation_probability ?? 0}%</strong>
            </div>
            <div>
              <span className="label">风</span>
              <strong>{first.wind_direction} {first.wind_speed}</strong>
            </div>
          </div>
          <p className="source-line">NWS updated {weather.updated_at}</p>
        </div>
      ) : (
        <p className="empty-text">目标区域确定后显示天气。</p>
      )}
    </DashboardCard>
  );
}
