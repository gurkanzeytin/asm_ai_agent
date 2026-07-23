import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ArrowDown } from "lucide-react";
import { ChatHeader } from "@/components/asm/ChatHeader";
import { ChatMessage } from "@/components/asm/ChatMessage";
import { EmptyState } from "@/components/asm/EmptyState";
import { InfoPanel } from "@/components/asm/InfoPanel";
import { PromptBox } from "@/components/asm/PromptBox";
import { Sidebar } from "@/components/asm/Sidebar";
import { SplashScreen } from "@/components/asm/SplashScreen";
import { Toaster } from "@/components/ui/sonner";
import { useChatController } from "@/hooks/use-chat-controller";
import { tr } from "@/locales/tr";
import { isNearScrollBottom } from "@/lib/scroll-utils";
import { uiTransition } from "@/lib/ui-motion";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Med Agent · Healthcare Intelligence" },
      {
        name: "description",
        content:
          "Premium AI assistant for healthcare organizations — analyze centers, query knowledge bases and generate reports in natural language.",
      },
      { property: "og:title", content: "Med Agent" },
      {
        property: "og:description",
        content: "Enterprise AI platform for healthcare intelligence.",
      },
    ],
  }),
  component: Index,
});

function Index() {
  const chat = useChatController();
  const [collapsed, setCollapsed] = useState(false);
  const [infoOpen, setInfoOpen] = useState(true);
  const [splashVisible, setSplashVisible] = useState(true);
  const [showJumpToLatest, setShowJumpToLatest] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const nearBottomRef = useRef(true);

  const scrollToLatest = (behavior: ScrollBehavior = "smooth") => {
    const element = scrollRef.current;
    if (!element) return;
    element.scrollTo({ top: element.scrollHeight, behavior });
    nearBottomRef.current = true;
    setShowJumpToLatest(false);
  };

  useEffect(() => {
    window.requestAnimationFrame(() => scrollToLatest("auto"));
  }, [chat.activeId]);

  useEffect(() => {
    if (nearBottomRef.current) {
      window.requestAnimationFrame(() => scrollToLatest());
    } else if (chat.messages.length > 0) {
      setShowJumpToLatest(true);
    }
  }, [chat.messages.length, chat.isGenerating, chat.animatedMessageId]);

  return (
    <div className="relative flex h-screen w-full overflow-hidden bg-background">
      <SplashScreen visible={splashVisible} onReady={() => setSplashVisible(false)} />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-70"
        style={{ background: "var(--gradient-hero)" }}
      />

      <Sidebar
        conversations={chat.conversations}
        activeId={chat.activeId}
        onSelect={chat.selectConversation}
        onNew={chat.newChat}
        onToggleFavorite={chat.toggleFavorite}
        onDelete={chat.deleteConversation}
        collapsed={collapsed}
        onToggleCollapse={() => setCollapsed((value) => !value)}
      />

      <main className="relative z-10 flex min-w-0 flex-1 flex-col">
        <ChatHeader
          title={chat.active?.title ?? tr.header.newConversation}
          onToggleInfo={() => setInfoOpen((value) => !value)}
          infoOpen={infoOpen}
        />

        <div
          ref={scrollRef}
          onScroll={(event) => {
            const nearBottom = isNearScrollBottom(event.currentTarget);
            nearBottomRef.current = nearBottom;
            if (nearBottom) setShowJumpToLatest(false);
          }}
          className="flex-1 overflow-y-auto"
        >
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={chat.activeId ?? "no-conversation"}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={uiTransition}
              className="min-h-full"
            >
              {chat.messages.length === 0 ? (
                <EmptyState />
              ) : (
                <div className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-8">
                  {chat.messages.map((message) => (
                    <ChatMessage
                      key={message.id}
                      message={message}
                      animateResponse={message.id === chat.animatedMessageId}
                      onPrompt={(prompt) => void chat.send(prompt)}
                      onEditPrompt={chat.setInput}
                    />
                  ))}
                </div>
              )}
            </motion.div>
          </AnimatePresence>
        </div>

        <AnimatePresence>
          {showJumpToLatest && (
            <motion.button
              type="button"
              initial={{ opacity: 0, y: 8, scale: 0.96 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 6, scale: 0.96 }}
              onClick={() => scrollToLatest()}
              className="absolute bottom-24 left-1/2 z-20 flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-border bg-background/95 px-3 py-1.5 text-xs font-medium text-foreground shadow-[var(--shadow-panel)] backdrop-blur-xl"
            >
              <ArrowDown className="h-3.5 w-3.5 text-primary" />
              {tr.chat.jumpToLatest}
            </motion.button>
          )}
        </AnimatePresence>

        <PromptBox
          value={chat.input}
          onChange={chat.setInput}
          onSend={() => void chat.send()}
          onStop={chat.stop}
          isGenerating={chat.isGenerating}
        />
      </main>

      <InfoPanel
        open={infoOpen}
        responseMs={chat.metrics.responseMs}
        isThinking={chat.isGenerating}
        sql={chat.lastSql}
      />

      <Toaster position="top-right" theme="light" visibleToasts={3} />
    </div>
  );
}
