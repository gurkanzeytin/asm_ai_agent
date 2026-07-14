import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Toaster } from "@/components/ui/sonner";
import { Sidebar } from "@/components/asm/Sidebar";
import { ChatHeader } from "@/components/asm/ChatHeader";
import { ChatMessage, TypingIndicator } from "@/components/asm/ChatMessage";
import { PromptBox } from "@/components/asm/PromptBox";
import { EmptyState } from "@/components/asm/EmptyState";
import { InfoPanel } from "@/components/asm/InfoPanel";
import { SettingsDialog } from "@/components/asm/SettingsDialog";
import { SplashScreen } from "@/components/asm/SplashScreen";
import type { Conversation, Message } from "@/components/asm/types";
import { ApiError, generateReport } from "@/lib/api";
import { tr } from "@/locales/tr";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "ASM AI Agent · Sağlık Zekâsı" },
      {
        name: "description",
        content:
          "Sağlık kurumları için yapay zekâ asistanı — merkezleri analiz edin, bilgi tabanında sorgular çalıştırın ve doğal dille raporlar oluşturun.",
      },
      { property: "og:title", content: "ASM AI Agent" },
      { property: "og:description", content: "Sağlık zekâsı için kurumsal yapay zekâ platformu." },
    ],
  }),
  component: Index,
});

import type { SqlResult } from "@/components/asm/SqlResultsTable";

function makeId() {
  return Math.random().toString(36).slice(2, 10);
}

function Index() {
  const [conversations, setConversations] = useState<Conversation[]>([
    {
      id: "c1",
      title: tr.sidebar.todaysPatientStatistics,
      messages: [],
      favorite: true,
      updatedAt: Date.now() - 1000 * 60 * 20,
    },
    {
      id: "c2",
      title: tr.sidebar.q3CenterPerformance,
      messages: [],
      updatedAt: Date.now() - 1000 * 60 * 60 * 3,
    },
    {
      id: "c3",
      title: tr.sidebar.busiestDoctorThisWeek,
      messages: [],
      updatedAt: Date.now() - 1000 * 60 * 60 * 24,
    },
  ]);
  const [activeId, setActiveId] = useState<string | null>("c1");
  const [collapsed, setCollapsed] = useState(false);
  const [infoOpen, setInfoOpen] = useState(true);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [input, setInput] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [showSplash, setShowSplash] = useState(true);
  const [lastResponseMs, setLastResponseMs] = useState(0);
  const [lastSql, setLastSql] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const active = conversations.find((c) => c.id === activeId) ?? null;
  const messages = active?.messages ?? [];

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages.length, isGenerating]);

  useEffect(() => {
    const timer = setTimeout(() => setShowSplash(false), 2000);
    return () => clearTimeout(timer);
  }, []);

  const updateConv = (id: string, fn: (c: Conversation) => Conversation) =>
    setConversations((list) => list.map((c) => (c.id === id ? fn(c) : c)));

  const send = (text?: string) => {
    const content = (text ?? input).trim();
    if (!content) return;

    let convId = activeId;
    if (!convId) {
      convId = makeId();
      const newConv: Conversation = {
        id: convId,
        title: content.slice(0, 40),
        messages: [],
        updatedAt: Date.now(),
      };
      setConversations((list) => [newConv, ...list]);
      setActiveId(convId);
    }

    const userMsg: Message = {
      id: makeId(),
      role: "user",
      content,
      createdAt: Date.now(),
    };
    const assistantId = makeId();

    updateConv(convId, (c) => ({
      ...c,
      title: c.messages.length === 0 ? content.slice(0, 40) : c.title,
      messages: [...c.messages, userMsg],
      updatedAt: Date.now(),
    }));
    setInput("");
    setIsGenerating(true);

    const cid = convId;
    const controller = new AbortController();
    abortRef.current = controller;

    void (async () => {
      try {
        const result = await generateReport(content, controller.signal);

        const answer =
          result.report?.markdown ??
          (result.success ? tr.chat.noReport : tr.chat.requestFailedFallback);

        let sqlResult: SqlResult | undefined;
        if (result.query_result && result.query_result.columns.length > 0) {
          sqlResult = {
            columns: result.query_result.columns,
            rows: result.query_result.rows,
            query: result.generated_sql ?? undefined,
            durationMs: result.timing?.execute_sql_ms ?? undefined,
          };
        }

        // Exact backend SQL (post-repair/validation) — shown in the info
        // panel even when execution failed after generation.
        setLastSql(result.generated_sql ?? null);

        const totalMs = result.timing?.total_ms ?? 0;
        if (totalMs > 0) {
          setLastResponseMs(Math.round(totalMs));
        }

        updateConv(cid, (c) => ({
          ...c,
          messages: [
            ...c.messages,
            {
              id: assistantId,
              role: "assistant",
              content: answer,
              createdAt: Date.now(),
              sqlResult,
            },
          ],
          updatedAt: Date.now(),
        }));

        toast.success(tr.chat.responseReady, {
          description: `${(totalMs / 1000).toFixed(2)}s`,
        });
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          return; // user pressed stop — nothing to render
        }
        setLastSql(null); // no response — don't show a previous question's SQL
        const description = error instanceof ApiError ? error.message : tr.chat.unexpectedError;
        toast.error(tr.chat.requestFailed, { description });
        updateConv(cid, (c) => ({
          ...c,
          messages: [
            ...c.messages,
            {
              id: assistantId,
              role: "assistant",
              content: `⚠️ ${description}`,
              createdAt: Date.now(),
            },
          ],
        }));
      } finally {
        setIsGenerating(false);
        abortRef.current = null;
      }
    })();
  };

  const stop = () => {
    abortRef.current?.abort();
    toast.warning(tr.chat.generationStopped);
  };

  const newChat = () => {
    const id = makeId();
    setConversations((list) => [
      { id, title: tr.sidebar.newChat, messages: [], updatedAt: Date.now() },
      ...list,
    ]);
    setActiveId(id);
  };

  const clearChat = () => {
    if (!activeId) return;
    updateConv(activeId, (c) => ({ ...c, messages: [] }));
    toast.info(tr.chat.chatCleared);
  };

  const del = (id: string) => {
    setConversations((list) => list.filter((c) => c.id !== id));
    if (activeId === id) setActiveId(null);
    toast.info(tr.chat.conversationDeleted);
  };

  const fav = (id: string) => updateConv(id, (c) => ({ ...c, favorite: !c.favorite }));

  return (
    <>
      <SplashScreen visible={showSplash} />
      <div className="relative flex h-screen w-full overflow-hidden bg-background">
        {/* Ambient gradient background */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-70"
          style={{ background: "var(--gradient-hero)" }}
        />

        <Sidebar
          conversations={conversations}
          activeId={activeId}
          onSelect={setActiveId}
          onNew={newChat}
          onToggleFavorite={fav}
          onDelete={del}
          onOpenSettings={() => setSettingsOpen(true)}
          collapsed={collapsed}
          onToggleCollapse={() => setCollapsed((v) => !v)}
        />

        <main className="relative z-10 flex min-w-0 flex-1 flex-col">
          <ChatHeader
            title={active?.title ?? tr.header.newConversation}
            onClear={clearChat}
            onToggleInfo={() => setInfoOpen((v) => !v)}
            infoOpen={infoOpen}
          />

          <div ref={scrollRef} className="flex-1 overflow-y-auto">
            {messages.length === 0 ? (
              <EmptyState onPick={(p) => send(p)} />
            ) : (
              <div className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-8">
                {messages.map((m) => (
                  <ChatMessage key={m.id} message={m} />
                ))}
                {isGenerating && messages[messages.length - 1]?.role === "user" && (
                  <TypingIndicator />
                )}
              </div>
            )}
          </div>

          <PromptBox
            value={input}
            onChange={setInput}
            onSend={() => send()}
            onStop={stop}
            isGenerating={isGenerating}
          />
        </main>

        <InfoPanel
          open={infoOpen}
          onClose={() => setInfoOpen(false)}
          responseMs={lastResponseMs}
          isThinking={isGenerating}
          sql={lastSql}
        />

        <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
        <Toaster position="top-right" theme="dark" />
      </div>
    </>
  );
}
