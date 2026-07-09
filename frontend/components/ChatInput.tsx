'use client';

import { KeyboardEvent, useEffect, useRef } from 'react';

interface Props {
  value: string;
  onChange: (val: string) => void;
  onSubmit: () => void;
  loading: boolean;
}

export default function ChatInput({ value, onChange, onSubmit, loading }: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  /* Auto-resize up to 200 px */
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 200) + 'px';
  }, [value]);

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!loading && value.trim()) onSubmit();
    }
  }

  return (
    <div className="max-w-3xl mx-auto w-full">
      <div className="flex items-end gap-3 bg-chat-card border border-chat-border rounded-2xl px-4 py-3 shadow-lg">
        <textarea
          ref={textareaRef}
          id="chat-input"
          rows={1}
          className="flex-1 bg-transparent text-chat-text placeholder-[#666] text-sm
                     resize-none outline-none leading-6 max-h-[200px]"
          placeholder="Ask anything about your database..."
          value={value}
          onChange={e => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={loading}
        />
        <button
          id="send-btn"
          onClick={onSubmit}
          disabled={loading || !value.trim()}
          aria-label="Send"
          className="flex-shrink-0 w-8 h-8 rounded-lg bg-chat-accent text-white
                     flex items-center justify-center
                     hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed
                     transition-opacity"
        >
          {/* Paper-plane send icon */}
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="currentColor"
            className="w-4 h-4"
          >
            <path d="M3.478 2.405a.75.75 0 00-.926.94l2.432 7.905H13.5a.75.75 0 010 1.5H4.984l-2.432 7.905a.75.75 0 00.926.94 60.519 60.519 0 0018.445-8.986.75.75 0 000-1.218A60.517 60.517 0 003.478 2.405z" />
          </svg>
        </button>
      </div>
      <p className="text-center text-xs text-[#555] mt-2">
        Enter to send · Shift + Enter for new line
      </p>
    </div>
  );
}
