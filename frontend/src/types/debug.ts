import type { TraceSummaryItem } from './chat';

export type TraceDebugResponse = {
  trace_id: string;
  trace_summary: TraceSummaryItem[];
};
