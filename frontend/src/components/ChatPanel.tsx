import { ChevronRight, MessageSquare } from 'lucide-react';
import { useState } from 'react';
import type { ChatMessage } from '../types/chat';

type Props = {
  messages: ChatMessage[];
  isLoading: boolean;
  onSend: (message: string) => void;
};

export function ChatPanel({ messages, isLoading, onSend }: Props) {
  const [draft, setDraft] = useState('');

  return (
    <aside className="chat-panel">
      <header className="chat-panel__header">
        <div className="chat-panel__icon"><MessageSquare size={19} /></div>
        <div>
          <h2>决策咨询</h2>
          <p>Session Active</p>
        </div>
      </header>

      <div className="chat-panel__messages">
        {messages.map((message) => (
          <article className={`chat-bubble chat-bubble--${message.role}`} key={message.id}>
            <p>{message.content}</p>
            {message.cards.length ? <span className="chat-bubble__meta">{message.cards.length} cards attached</span> : null}
          </article>
        ))}
        {isLoading ? (
          <article className="chat-bubble chat-bubble--assistant chat-bubble--loading">
            <span /> <span /> <span />
          </article>
        ) : null}
      </div>

      <form
        className="chat-panel__form"
        onSubmit={(event) => {
          event.preventDefault();
          if (!draft.trim()) return;
          onSend(draft.trim());
          setDraft('');
        }}
      >
        <input value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="询问区域详情、天气或通勤..." />
        <button type="submit" aria-label="Send message"><ChevronRight size={20} /></button>
      </form>
    </aside>
  );
}
