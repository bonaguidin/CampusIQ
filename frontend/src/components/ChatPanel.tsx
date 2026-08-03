import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { useAuth } from '../auth/useAuth';
import { sendChat, type ChatMessage } from '../api/chat';
import './ChatPanel.css';

const SUGGESTIONS = [
  'What are my biggest skill gaps for my target roles?',
  'Which courses should I prioritize next term?',
  'How ready am I for an internship right now?',
];

export function ChatPanel() {
  const { slug, profile } = useAuth();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const firstName = profile?.student?.name?.split(' ')[0] ?? 'there';

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
  }, [messages, sending]);

  async function submit(text: string) {
    const trimmed = text.trim();
    if (!trimmed || sending || !slug) return;
    setError(null);
    const priorHistory = messages;
    setMessages((m) => [...m, { role: 'user', content: trimmed }]);
    setInput('');
    setSending(true);
    try {
      const reply = await sendChat(slug, trimmed, priorHistory);
      setMessages((m) => [...m, { role: 'assistant', content: reply }]);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong. Try again.');
    } finally {
      setSending(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void submit(input);
  }

  return (
    <section className="chat-panel" aria-label="Ask GradusIQ">
      <div className="chat-header">
        <span className="chat-title">Ask GradusIQ</span>
        <span className="chat-sub">
          Chat about your academics &amp; career — grounded in your profile and analysis.
        </span>
      </div>

      <div className="chat-messages" ref={listRef}>
        {messages.length === 0 && (
          <div className="chat-empty">
            <p className="chat-empty-lead">
              Hi {firstName} — ask me anything about your record, gaps, or next steps.
            </p>
            <div className="chat-suggestions">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  className="chat-chip"
                  onClick={() => void submit(s)}
                  disabled={sending || !slug}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className={`chat-msg chat-msg--${m.role}`}>
            <span className="chat-msg-role">{m.role === 'user' ? 'You' : 'GradusIQ'}</span>
            <div className="chat-msg-body">{m.content}</div>
          </div>
        ))}

        {sending && (
          <div className="chat-msg chat-msg--assistant">
            <span className="chat-msg-role">GradusIQ</span>
            <div className="chat-msg-body chat-typing" aria-label="Thinking">
              <span />
              <span />
              <span />
            </div>
          </div>
        )}
      </div>

      {error && (
        <div className="chat-error" role="alert">
          {error}
        </div>
      )}

      <form className="chat-input-row" onSubmit={onSubmit}>
        <input
          className="chat-input"
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about your grades, gaps, roles…"
          disabled={sending || !slug}
          aria-label="Message GradusIQ"
        />
        <button
          type="submit"
          className="btn btn-primary btn-sm"
          disabled={sending || !input.trim() || !slug}
        >
          {sending ? '…' : 'Send'}
        </button>
      </form>
    </section>
  );
}
