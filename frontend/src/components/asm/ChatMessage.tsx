import { AnimatePresence, motion } from "motion/react";
import { lazy, Suspense, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  AlertTriangle,
  Check,
  ChevronRight,
  Copy,
  DatabaseZap,
  Pencil,
  RefreshCw,
  ServerCrash,
  User,
  WifiOff,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import type { Message } from "./types";
import { tr } from "@/locales/tr";
import { MedAgentLogo } from "./MedAgentLogo";
import { useAnimatedText } from "@/components/ui/animated-text";
import { TextShimmer } from "./TextShimmer";
import type { WorkflowStage } from "@/lib/api";
import type { MessageErrorKind } from "./types";
import { panelTransition, quickTransition, uiTransition } from "@/lib/ui-motion";
import { traceChatRuntime } from "@/lib/chat-runtime-trace";

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
  const metricContext = (() => {
    const cards = message.metricCards ?? [];
    const context = cards[0]?.context;
    return context && cards.every((card) => card.context === context) ? context : undefined;
  })();
  const returnsLoadingPlaceholder = !isUser && Boolean(message.streaming) && !message.content;
  traceChatRuntime("chat-message-render", {
    messageId: message.id,
    role: message.role,
    streaming: message.streaming ?? false,
    status: message.status ?? null,
    contentLength: message.content.length,
    outcome: message.outcome ?? null,
    rowCount: message.rowCount ?? null,
    returnsNull: false,
    returnsLoadingPlaceholder,
  });

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error(tr.common.copyFailed);
    }
  };

  if (returnsLoadingPlaceholder) {
    return <TypingIndicator stage={message.progressStage} />;
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={uiTransition}
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
          ) : message.status === "error" ? (
            <ResponseError kind={message.errorKind ?? "server"} />
          ) : message.streaming ? (
            <AssistantText content={message.content} streaming animate={animateResponse} />
          ) : (
            <AssistantText content={message.content} animate={animateResponse} />
          )}
        </div>
        {!isUser && !message.streaming && message.metricCards && message.metricCards.length > 0 && (
          <div className="w-full">
            <div className="mb-2 flex min-w-0 items-baseline gap-2">
              <p className="shrink-0 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                {tr.chat.keyMetrics}
              </p>
              {metricContext && (
                <span
                  className="truncate text-[11px] text-muted-foreground/70"
                  title={metricContext}
                >
                  {metricContext}
                </span>
              )}
            </div>
            <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
              {message.metricCards.map((card) => {
                const valueLength = Array.from(card.value).length;
                return (
                  <div
                    key={`${card.context ?? "metric"}-${card.label}`}
                    className="glass flex min-h-[104px] min-w-0 flex-col rounded-lg border border-border/60 px-3.5 py-3"
                  >
                    <div
                      className={cn(
                        "line-clamp-2 min-h-10 overflow-hidden break-words font-semibold [overflow-wrap:anywhere]",
                        valueLength > 32
                          ? "text-xs leading-5"
                          : valueLength > 18
                            ? "text-sm leading-5"
                            : "text-lg leading-5",
                        card.isEmpty ? "text-muted-foreground" : "text-foreground",
                      )}
                      title={card.value}
                    >
                      {card.value}
                    </div>
                    <div
                      className="mt-auto line-clamp-2 min-h-8 overflow-hidden break-words pt-2 text-[11px] font-medium leading-4 text-muted-foreground [overflow-wrap:anywhere]"
                      title={card.label}
                    >
                      {card.label}
                    </div>
                  </div>
                );
              })}
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
                  transition={panelTransition}
                  className="overflow-hidden"
                >
                  <div className="mt-2 w-full">
                    {(message.sqlResult.technicalRowCount != null ||
                      message.sqlResult.resultShape) && (
                      <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1 rounded-md border border-border/50 bg-muted/20 px-3 py-2 text-[11px] text-muted-foreground">
                        {message.sqlResult.technicalRowCount != null && (
                          <span>SQL sonuç satırı: {message.sqlResult.technicalRowCount}</span>
                        )}
                        {message.sqlResult.resultShape && (
                          <span>Sonuç şekli: {message.sqlResult.resultShape}</span>
                        )}
                      </div>
                    )}
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
            {message.prompt && (message.status === "error" || message.status === "stopped") && (
              <button
                type="button"
                onClick={() => onPrompt?.(message.prompt ?? "")}
                className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                <RefreshCw className="h-3 w-3" />
                {tr.chat.retry}
              </button>
            )}
            {message.status === "error" && message.errorKind === "query" && message.prompt && (
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

export function TypingIndicator({ stage }: { stage?: WorkflowStage }) {
  const label = stage ? tr.chat.workflowStages[stage] : tr.chat.thinking;

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
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={label}
            initial={{ opacity: 0, y: 3 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -3 }}
            transition={quickTransition}
          >
            <TextShimmer
              duration={1.55}
              spread={1.4}
              className="text-xs font-medium [--base-color:var(--muted-foreground)] [--base-gradient-color:var(--foreground)]"
            >
              {label}
            </TextShimmer>
          </motion.div>
        </AnimatePresence>
      </div>
    </motion.div>
  );
}

const errorIcons: Record<MessageErrorKind, typeof AlertTriangle> = {
  network: WifiOff,
  query: DatabaseZap,
  server: ServerCrash,
  invalid: AlertTriangle,
};

function ResponseError({ kind }: { kind: MessageErrorKind }) {
  const Icon = errorIcons[kind];
  const copy = tr.chat.errors[kind];
  return (
    <div className="flex max-w-xl items-start gap-3 border-l-2 border-destructive/60 bg-destructive/5 px-3 py-2.5">
      <Icon className="mt-0.5 h-4 w-4 shrink-0 text-destructive" aria-hidden="true" />
      <div>
        <p className="font-medium text-foreground">{copy.title}</p>
        <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">{copy.description}</p>
      </div>
    </div>
  );
}
