import { AnimatePresence, motion } from "motion/react";
import { lazy, Suspense, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { User, Copy, Check, ChevronRight, RefreshCw, Pencil } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import type { Message } from "./types";
import { tr } from "@/locales/tr";
import { MedAgentLogo } from "./MedAgentLogo";
import { useAnimatedText } from "@/components/ui/animated-text";
import { TextShimmer } from "./TextShimmer";

const LazySqlResultsTable = lazy(() =>
  import("./SqlResultsTable").then((module) => ({ default: module.SqlResultsTable })),
);

export function ChatMessage({
  message,
  animateResponse = false,
  onPrompt,
  onEditPrompt,
}: {
  message: Message;
  animateResponse?: boolean;
  onPrompt?: (prompt: string) => void;
  onEditPrompt?: (prompt: string) => void;
}) {
  const isUser = message.role === "user";
  const [copied, setCopied] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error(tr.common.copyFailed);
    }
  };

  if (!isUser && message.streaming && !message.content) return <TypingIndicator />;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className={cn("group flex gap-3", isUser && "flex-row-reverse")}
    >
      <div
        className={cn(
          "shrink-0",
          isUser
            ? "grid h-8 w-8 place-items-center rounded-lg bg-primary/20 text-primary"
            : "flex h-9 w-9 items-start justify-center",
        )}
      >
        {isUser ? (
          <User className="h-4 w-4" />
        ) : (
          <span aria-hidden="true">
            <MedAgentLogo size={36} noIntro />
          </span>
        )}
      </div>

      <div
        className={cn(
          "flex min-w-0 flex-col gap-1.5",
          message.sqlResult ? "max-w-full flex-1" : "max-w-[80%]",
          isUser && "items-end",
        )}
      >
        <div
          className={cn(
            "text-sm leading-relaxed",
            isUser
              ? "rounded-2xl rounded-tr-sm bg-primary px-4 py-3 text-primary-foreground"
              : "text-foreground",
          )}
        >
          {isUser ? (
            <p className="whitespace-pre-wrap">{message.content}</p>
          ) : message.streaming ? (
            <AssistantText content={message.content} streaming animate={animateResponse} />
          ) : (
            <AssistantText content={message.content} animate={animateResponse} />
          )}
        </div>
        {!isUser && !message.streaming && message.metricCards && message.metricCards.length > 0 && (
          <div className="w-full">
            <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              {tr.chat.keyMetrics}
            </p>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
              {message.metricCards.map((card) => (
                <div
                  key={card.label}
                  className="glass rounded-xl border border-border/60 px-3 py-2.5"
                >
                  <div className="text-base font-semibold text-foreground">{card.value}</div>
                  <div className="mt-0.5 text-[11px] leading-tight text-muted-foreground">
                    {card.label}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
        {!isUser && message.showSqlTable && message.sqlResult && !message.streaming && (
          <div className="w-full">
            <button
              type="button"
              onClick={() => setDetailsOpen((open) => !open)}
              aria-expanded={detailsOpen}
              className="flex items-center gap-1.5 rounded-md px-1 py-1 text-[11px] font-medium text-muted-foreground transition hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
            >
              <ChevronRight
                className={cn("h-3.5 w-3.5 transition-transform", detailsOpen && "rotate-90")}
                aria-hidden="true"
              />
              {tr.chat.technicalDetails}
            </button>
            <AnimatePresence initial={false}>
              {detailsOpen && (
                <motion.div
                  initial={{ height: 0, opacity: 0, y: -4 }}
                  animate={{ height: "auto", opacity: 1, y: 0 }}
                  exit={{ height: 0, opacity: 0, y: -4 }}
                  transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
                  className="overflow-hidden"
                >
                  <div className="mt-2 w-full">
                    <Suspense
                      fallback={<div className="h-24 animate-pulse rounded-lg bg-muted/40" />}
                    >
                      <LazySqlResultsTable data={message.sqlResult} />
                    </Suspense>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )}
        {!isUser && !message.streaming && (
          <div
            className={cn(
              "flex items-center gap-1 transition",
              message.status === "error" || message.status === "stopped"
                ? "opacity-100"
                : "opacity-0 group-hover:opacity-100 group-focus-within:opacity-100",
            )}
          >
            <button
              onClick={copy}
              aria-label={tr.common.copy}
              className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
              {copied ? tr.common.copied : tr.common.copy}
            </button>
            {message.prompt &&
              (message.status === "error" || message.status === "stopped") && (
              <button
                type="button"
                onClick={() => onPrompt?.(message.prompt ?? "")}
                className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                <RefreshCw className="h-3 w-3" />
                {tr.chat.retry}
              </button>
            )}
            {message.status === "error" && message.prompt && (
              <button
                type="button"
                onClick={() => onEditPrompt?.(message.prompt ?? "")}
                className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                <Pencil className="h-3 w-3" />
                {tr.chat.editQuestion}
              </button>
            )}
          </div>
        )}
      </div>
    </motion.div>
  );
}

function AssistantText({
  content,
  streaming = false,
  animate = false,
}: {
  content: string;
  streaming?: boolean;
  animate?: boolean;
}) {
  const animatedContent = useAnimatedText(content, "", 0.012, animate, 1200);

  return (
    <div className="prose-chat">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ className, children, ...props }) {
            const isBlock = className?.includes("language-");
            if (isBlock) {
              return (
                <pre className="my-2 overflow-x-auto rounded-lg border border-border bg-background/60 p-3 text-xs">
                  <code {...props}>{children}</code>
                </pre>
              );
            }
            return (
              <code className="rounded bg-background/60 px-1.5 py-0.5 text-xs text-cyan" {...props}>
                {children}
              </code>
            );
          },
          table({ children }) {
            return (
              <div className="my-2 overflow-x-auto rounded-lg border border-border">
                <table className="w-full text-xs">{children}</table>
              </div>
            );
          },
          th({ children }) {
            return (
              <th className="border-b border-border bg-background/40 px-3 py-2 text-left font-medium">
                {children}
              </th>
            );
          },
          td({ children }) {
            return <td className="border-b border-border/50 px-3 py-2">{children}</td>;
          },
          a({ children, href }) {
            return (
              <a href={href} className="text-primary underline-offset-2 hover:underline">
                {children}
              </a>
            );
          },
          ul({ children }) {
            return <ul className="my-2 list-disc space-y-1 pl-5">{children}</ul>;
          },
          ol({ children }) {
            return <ol className="my-2 list-decimal space-y-1 pl-5">{children}</ol>;
          },
          p({ children }) {
            return <p className="my-1.5 whitespace-pre-wrap first:mt-0 last:mb-0">{children}</p>;
          },
          h1: ({ children }) => (
            <h1 className="mt-3 text-lg font-semibold first:mt-0">{children}</h1>
          ),
          h2: ({ children }) => (
            <h2 className="mt-3 text-base font-semibold first:mt-0">{children}</h2>
          ),
          h3: ({ children }) => (
            <h3 className="mt-2 text-sm font-semibold first:mt-0">{children}</h3>
          ),
        }}
      >
        {animatedContent}
      </ReactMarkdown>
      {streaming && (
        <motion.span
          aria-hidden="true"
          className="ml-0.5 inline-block h-[1em] w-[2px] translate-y-[2px] bg-current align-middle"
          animate={{ opacity: [1, 1, 0, 0] }}
          transition={{ duration: 1, repeat: Infinity, ease: "linear", times: [0, 0.5, 0.5, 1] }}
        />
      )}
    </div>
  );
}

export function TypingIndicator() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex items-center gap-3"
    >
      <div className="flex h-10 w-10 shrink-0 items-center justify-center">
        <span aria-hidden="true">
          <MedAgentLogo size={38} noIntro />
        </span>
      </div>
      <div className="flex h-10 items-center px-1">
        <TextShimmer
          duration={1.55}
          spread={1.4}
          className="text-xs font-medium [--base-color:var(--muted-foreground)] [--base-gradient-color:var(--foreground)]"
        >
          {tr.chat.thinking}
        </TextShimmer>
      </div>
    </motion.div>
  );
}
