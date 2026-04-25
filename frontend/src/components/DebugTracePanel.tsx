import type { TraceSummaryItem } from '../types/chat';

type Props = {
  trace: TraceSummaryItem[];
  isOpen: boolean;
  onToggle: () => void;
};

export function DebugTracePanel({ trace, isOpen, onToggle }: Props) {
  return (
    <aside className={`debug-panel ${isOpen ? 'debug-panel--open' : ''}`} onMouseDown={(event) => event.stopPropagation()} onWheel={(event) => event.stopPropagation()}>
      <button type="button" onClick={onToggle}>
        DEBUG_TRACE {isOpen ? '[-]' : '[+]'}
      </button>
      {isOpen ? (
        <div className="debug-panel__body">
          {trace.length ? trace.map((item, index) => (
            <div key={`${item.step}-${index}`}>
              <span>[{item.service}]</span> {item.step} / {item.status} / {item.latency_ms}ms {item.mcp ? `/ ${item.mcp}` : ''}
            </div>
          )) : <div>No trace yet.</div>}
        </div>
      ) : null}
    </aside>
  );
}
