import { Activity } from 'lucide-react';
import { DashboardCard } from './DashboardCard';
import type { AreaMetricsResponse } from '../types/area';

type Props = {
  metrics: AreaMetricsResponse | null;
  isExpanded: boolean;
  onToggle: (id: string) => void;
};

export function AreaMetricsCards({ metrics, isExpanded, onToggle }: Props) {
  return (
    <DashboardCard id="metrics" title="区域指标" icon={Activity} isExpanded={isExpanded} onToggle={onToggle}>
      <div className="metrics-panel">
        {metrics?.metric_cards.map((card) => (
          <article className="metric-card" key={card.title}>
            <div>
              <h4>{card.title}</h4>
              <p>{card.subtitle}</p>
            </div>
            <strong>{card.score_label ?? card.metrics[0]?.value}</strong>
            <div className="metric-card__values">
              {card.metrics.map((item) => (
                <span key={item.label}>
                  {item.label}: <b>{item.value}</b>{item.unit ? ` ${item.unit}` : ''}
                </span>
              ))}
            </div>
          </article>
        )) ?? <p className="empty-text">目标区域确定后显示指标。</p>}
        {metrics ? <p className="source-line">Updated {metrics.updated_at}</p> : null}
      </div>
    </DashboardCard>
  );
}
