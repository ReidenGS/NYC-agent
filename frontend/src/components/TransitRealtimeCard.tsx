import { Train } from 'lucide-react';
import { DashboardCard } from './DashboardCard';
import type { TransitRealtimeResponse } from '../types/transit';

type Props = {
  transit: TransitRealtimeResponse | null;
  isExpanded: boolean;
  onToggle: (id: string) => void;
};

export function TransitRealtimeCard({ transit, isExpanded, onToggle }: Props) {
  return (
    <DashboardCard id="transit" title="实时通勤" icon={Train} variant="dark" isExpanded={isExpanded} onToggle={onToggle} badge="LIVE">
      {transit ? (
        <div className="transit-panel">
          <div className="transit-summary">
            <span>{transit.origin_stop} {'->'} {transit.destination}</span>
            <strong>{transit.total_minutes} min</strong>
          </div>
          <div className="transit-timeline">
            <span>步行 {transit.walking_to_stop_minutes}m</span>
            <span>等车 {transit.waiting_minutes}m</span>
            <span>车上 {transit.in_vehicle_minutes}m</span>
          </div>
          {transit.departures.map((departure) => (
            <div className="departure-row" key={`${departure.route_id}-${departure.departure_time}`}>
              <b>{departure.route_id}</b>
              <span>{departure.stop_name}</span>
              <strong>{departure.minutes_until_departure} min</strong>
            </div>
          ))}
          <p className="source-line">{transit.realtime_used ? '实时数据' : '非实时 fallback'}</p>
        </div>
      ) : (
        <p className="empty-text">设置目的地后显示实时通勤。</p>
      )}
    </DashboardCard>
  );
}
