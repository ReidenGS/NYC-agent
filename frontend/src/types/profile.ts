export type Budget = {
  min: number | null;
  max: number | null;
  currency?: string;
};

export type DecisionWeights = {
  safety: number;
  commute: number;
  rent: number;
  convenience: number;
  entertainment: number;
};

export type TargetArea = {
  area_id: string;
  area_name: string;
  borough?: string;
};

export type ProfileSnapshot = {
  session_id: string;
  target_area: TargetArea | null;
  target_area_id?: string | null;
  budget?: Budget | null;
  target_destination?: string | null;
  max_commute_minutes?: number | null;
  preferences?: string[];
  weights: DecisionWeights;
  missing_required_fields: string[];
  conversation_summary: string;
  updated_at: string;
};

export type SessionCreateResponse = {
  session_id: string;
  profile_snapshot: ProfileSnapshot;
};
