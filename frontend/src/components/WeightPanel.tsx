import { BarChart3 } from 'lucide-react';
import { DashboardCard } from './DashboardCard';
import type { DecisionWeights } from '../types/profile';

type Props = {
  weights: DecisionWeights | null;
  isExpanded: boolean;
  onToggle: (id: string) => void;
};

const labels: Record<keyof DecisionWeights, string> = {
  safety: '安全',
  commute: '通勤',
  rent: '租金',
  convenience: '便利',
  entertainment: '娱乐'
};

const defaultWeights: DecisionWeights = {
  safety: 0.3,
  commute: 0.3,
  rent: 0.2,
  convenience: 0.1,
  entertainment: 0.1
};

export function WeightPanel({ weights, isExpanded, onToggle }: Props) {
  const data = weights ?? defaultWeights;

  return (
    <DashboardCard id="weights" title="权重模型" icon={BarChart3} isExpanded={isExpanded} onToggle={onToggle}>
      <div className="weight-list">
        {(Object.keys(labels) as Array<keyof DecisionWeights>).map((key) => {
          const value = data[key];
          return (
            <div className="weight-row" key={key}>
              <div className="weight-row__meta">
                <span>{labels[key]}</span>
                <strong>{Math.round(value * 100)}%</strong>
              </div>
              <div className="weight-row__track">
                <span style={{ width: `${Math.round(value * 100)}%` }} />
              </div>
            </div>
          );
        })}
      </div>
    </DashboardCard>
  );
}
