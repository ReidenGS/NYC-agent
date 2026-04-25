import type { ReactNode } from 'react';
import { Maximize2, Minimize2, type LucideIcon } from 'lucide-react';

type DashboardCardProps = {
  id: string;
  title: string;
  icon?: LucideIcon;
  isExpanded: boolean;
  onToggle: (id: string) => void;
  children: ReactNode;
  badge?: string;
  variant?: 'light' | 'dark';
};

export function DashboardCard({ id, title, icon: Icon, isExpanded, onToggle, children, badge, variant = 'light' }: DashboardCardProps) {
  return (
    <section
      className={`dashboard-card dashboard-card--${variant} ${isExpanded ? 'dashboard-card--expanded' : ''}`}
      onClick={(event) => {
        event.stopPropagation();
        onToggle(id);
      }}
      onMouseDown={(event) => event.stopPropagation()}
      onWheel={(event) => event.stopPropagation()}
    >
      <header className="dashboard-card__header">
        <div className="dashboard-card__title-row">
          {Icon ? <Icon size={15} /> : null}
          <h3>{title}</h3>
        </div>
        <div className="dashboard-card__actions">
          {badge ? <span className="dashboard-card__badge">{badge}</span> : null}
          {isExpanded ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
        </div>
      </header>
      <div className="dashboard-card__body">{children}</div>
      {!isExpanded ? <p className="dashboard-card__hint">点击查看详细指标</p> : null}
    </section>
  );
}
