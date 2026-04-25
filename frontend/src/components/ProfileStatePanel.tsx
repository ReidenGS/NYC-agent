import { User } from 'lucide-react';
import { DashboardCard } from './DashboardCard';
import type { ProfileSnapshot } from '../types/profile';

type Props = {
  profile: ProfileSnapshot | null;
  isExpanded: boolean;
  onToggle: (id: string) => void;
};

export function ProfileStatePanel({ profile, isExpanded, onToggle }: Props) {
  const targetArea = profile?.target_area;
  const missing = profile?.missing_required_fields ?? ['target_area'];

  return (
    <DashboardCard id="profile" title="已感知需求" icon={User} isExpanded={isExpanded} onToggle={onToggle}>
      <div className="profile-panel">
        <div className="pill-row">
          {targetArea ? (
            <span className="pill pill--primary">{targetArea.area_name}</span>
          ) : (
            <span className="pill pill--danger">缺少 target_area</span>
          )}
          {targetArea?.borough ? <span className="pill">{targetArea.borough}</span> : null}
        </div>

        <div className="info-grid">
          <div>
            <span className="label">预算</span>
            <strong>
              {profile?.budget?.max ? `$${profile.budget.min ?? 0}-${profile.budget.max}` : '未提供'}
            </strong>
          </div>
          <div>
            <span className="label">目的地</span>
            <strong>{profile?.target_destination ?? '未提供'}</strong>
          </div>
          <div>
            <span className="label">最长通勤</span>
            <strong>{profile?.max_commute_minutes ? `${profile.max_commute_minutes} min` : '未提供'}</strong>
          </div>
          <div>
            <span className="label">缺失字段</span>
            <strong>{missing.length ? missing.join(', ') : '无'}</strong>
          </div>
        </div>

        <div className="summary-box">
          <span className="label">会话摘要</span>
          <p>{profile?.conversation_summary || 'Agent 会在多轮对话后生成短摘要。'}</p>
        </div>
      </div>
    </DashboardCard>
  );
}
