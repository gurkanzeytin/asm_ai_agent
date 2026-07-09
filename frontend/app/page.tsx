'use client';

import { useEffect, useRef, useState } from 'react';
import axios from 'axios';

import { generateReport } from '@/services/api';
import ChatInput from '@/components/ChatInput';
import ChatMessage, { Message } from '@/components/ChatMessage';

/* ─── Static sidebar conversations ─── */
const STATIC_CONVERSATIONS = ['Conversation 1', 'Conversation 2', 'Conversation 3'];

/* ─── Stage-aware loading indicator (honest — no simulated completion) ─── */
const LOADING_STAGES = [
  'Retrieving schema…',
  'Generating SQL…',
  'Executing query…',
  'Generating report…',
];
// Approximate stage durations (ms) for label cycling — purely cosmetic
const STAGE_DELAYS = [2000, 0, 0, 0]; // schema is fast; rest fill remaining time

function WorkflowLoadingIndicator() {
  const [stageIdx, setStageIdx] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    function advance(idx: number) {
      const delay = STAGE_DELAYS[idx];
      if (delay > 0 && idx + 1 < LOADING_STAGES.length) {
        timer = setTimeout(() => {
          if (!cancelled) {
            setStageIdx(idx + 1);
            advance(idx + 1);
          }
        }, delay);
      }
    }

    advance(0);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);

  return (
    <div className="mb-8">
      <div className="flex items-center gap-2 mb-3">
        {/* Avatar */}
        <div className="w-7 h-7 rounded-full bg-chat-accent flex items-center justify-center flex-shrink-0">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-4 h-4 text-white">
            <path fillRule="evenodd" d="M9 4.5a.75.75 0 01.721.544l.813 2.846a3.75 3.75 0 002.576 2.576l2.846.813a.75.75 0 010 1.442l-2.846.813a3.75 3.75 0 00-2.576 2.576l-.813 2.846a.75.75 0 01-1.442 0l-.813-2.846a3.75 3.75 0 00-2.576-2.576l-2.846-.813a.75.75 0 010-1.442l2.846-.813A3.75 3.75 0 007.466 7.89l.813-2.846A.75.75 0 019 4.5zM18 1.5a.75.75 0 01.728.568l.258 1.036c.236.94.97 1.674 1.91 1.91l1.036.258a.75.75 0 010 1.456l-1.036.258c-.94.236-1.674.97-1.91 1.91l-.258 1.036a.75.75 0 01-1.456 0l-.258-1.036a2.625 2.625 0 00-1.91-1.91l-1.036-.258a.75.75 0 010-1.456l1.036-.258a2.625 2.625 0 001.91-1.91l.258-1.036A.75.75 0 0118 1.5z" clipRule="evenodd" />
          </svg>
        </div>
        <span className="text-sm font-semibold text-chat-text">Assistant</span>
      </div>
      {/* Honest stage label — no fake checkmarks */}
      <div
        id="loading-indicator"
        className="ml-9 flex items-center gap-2 h-7"
        aria-label="Processing"
        aria-live="polite"
      >
        <span className="inline-block w-2 h-2 rounded-full bg-chat-accent animate-pulse" />
        <span className="text-sm text-[#888] transition-all duration-500">
          {LOADING_STAGES[stageIdx]}
        </span>
      </div>
    </div>
  );
}

/* ─── Sidebar ─── */
function Sidebar() {
  return (
    <aside className="w-64 flex-shrink-0 bg-chat-sidebar border-r border-chat-border flex flex-col">
      {/* Logo / title */}
      <div className="px-4 pt-5 pb-4">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-md bg-chat-accent flex items-center justify-center">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 24 24"
              fill="currentColor"
              className="w-3.5 h-3.5 text-white"
            >
              <path
                fillRule="evenodd"
                d="M9 4.5a.75.75 0 01.721.544l.813 2.846a3.75 3.75 0 002.576 2.576l2.846.813a.75.75 0 010 1.442l-2.846.813a3.75 3.75 0 00-2.576 2.576l-.813 2.846a.75.75 0 01-1.442 0l-.813-2.846a3.75 3.75 0 00-2.576-2.576l-2.846-.813a.75.75 0 010-1.442l2.846-.813A3.75 3.75 0 007.466 7.89l.813-2.846A.75.75 0 019 4.5z"
                clipRule="evenodd"
              />
            </svg>
          </div>
          <span className="text-sm font-semibold text-chat-text truncate">ASM AI Reporting Agent</span>
        </div>
      </div>

      {/* New Chat button */}
      <div className="px-3 pb-3">
        <button
          id="new-chat-btn"
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-chat-text
                     border border-chat-border hover:bg-chat-card transition-colors"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
            strokeWidth={1.5}
            stroke="currentColor"
            className="w-4 h-4"
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
          </svg>
          New Chat
        </button>
      </div>

      {/* Static conversation list */}
      <nav className="flex-1 px-3 overflow-y-auto">
        <p className="text-xs text-[#555] px-2 mb-2 mt-1 font-medium uppercase tracking-wider">Recent</p>
        {STATIC_CONVERSATIONS.map((conv, i) => (
          <button
            key={i}
            id={`conv-${i + 1}`}
            className="w-full text-left px-3 py-2 rounded-lg text-sm text-[#888]
                       hover:bg-chat-card hover:text-chat-text transition-colors truncate"
          >
            {conv}
          </button>
        ))}
      </nav>
    </aside>
  );
}

/* ─── Welcome screen (shown when no messages exist) ─── */
function WelcomeScreen() {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center px-4 select-none">
      <div className="w-14 h-14 rounded-2xl bg-chat-accent flex items-center justify-center mb-5 shadow-lg">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="currentColor"
          className="w-7 h-7 text-white"
        >
          <path
            fillRule="evenodd"
            d="M9 4.5a.75.75 0 01.721.544l.813 2.846a3.75 3.75 0 002.576 2.576l2.846.813a.75.75 0 010 1.442l-2.846.813a3.75 3.75 0 00-2.576 2.576l-.813 2.846a.75.75 0 01-1.442 0l-.813-2.846a3.75 3.75 0 00-2.576-2.576l-2.846-.813a.75.75 0 010-1.442l2.846-.813A3.75 3.75 0 007.466 7.89l.813-2.846A.75.75 0 019 4.5zM18 1.5a.75.75 0 01.728.568l.258 1.036c.236.94.97 1.674 1.91 1.91l1.036.258a.75.75 0 010 1.456l-1.036.258c-.94.236-1.674.97-1.91 1.91l-.258 1.036a.75.75 0 01-1.456 0l-.258-1.036a2.625 2.625 0 00-1.91-1.91l-1.036-.258a.75.75 0 010-1.456l1.036-.258a2.625 2.625 0 001.91-1.91l.258-1.036A.75.75 0 0118 1.5z"
            clipRule="evenodd"
          />
        </svg>
      </div>
      <h2 className="text-2xl font-semibold text-chat-text mb-2">ASM AI Reporting Agent</h2>
      <p className="text-[#777] text-sm max-w-xs">
        Ask questions about your database. The agent will generate SQL, run it, and produce a report.
      </p>
    </div>
  );
}

/* ─── Page ─── */
export default function HomePage() {
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  /* Auto-scroll to latest message */
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading, error]);

  async function handleQuestion() {
    const question = input.trim();
    if (!question || loading) return;

    setInput('');
    setError(null);
    setMessages(prev => [...prev, { role: 'user', content: question }]);
    setLoading(true);

    try {
      const data = await generateReport(question);
      setMessages(prev => [...prev, { role: 'assistant', data }]);
    } catch (err: unknown) {
      console.error("Error in handleQuestion:", err);
      let msg = 'Unexpected error.';
      if (axios.isAxiosError(err)) {
        const detail =
          err.response?.data?.detail ??
          err.response?.data?.message ??
          err.message;
        msg = typeof detail === 'string' ? detail : JSON.stringify(detail);
      } else if (err instanceof Error) {
        msg = err.message;
      }
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  const isEmpty = messages.length === 0 && !loading && !error;

  return (
    <div className="flex h-screen bg-chat-bg text-chat-text overflow-hidden">
      <Sidebar />

      {/* ── Main area ── */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Messages / welcome */}
        <div className="flex-1 overflow-y-auto">
          {isEmpty ? (
            <WelcomeScreen />
          ) : (
            <div className="max-w-3xl mx-auto w-full px-4 pt-8 pb-4">
              {messages.map((msg, i) => (
                <ChatMessage key={i} message={msg} />
              ))}

              {loading && <WorkflowLoadingIndicator />}

              {error && (
                <div
                  id="error-display"
                  className="mb-6 rounded-xl border border-red-800 bg-red-950/40
                             px-4 py-3 text-sm text-red-400"
                >
                  <p className="font-semibold mb-1">Failed to generate report.</p>
                  <p className="font-mono text-xs break-words">{error}</p>
                </div>
              )}

              <div ref={bottomRef} />
            </div>
          )}
        </div>

        {/* ── Fixed input bar ── */}
        <div className="px-4 pb-6 pt-3 border-t border-chat-border bg-chat-bg">
          <ChatInput
            value={input}
            onChange={setInput}
            onSubmit={handleQuestion}
            loading={loading}
          />
        </div>
      </div>
    </div>
  );
}
