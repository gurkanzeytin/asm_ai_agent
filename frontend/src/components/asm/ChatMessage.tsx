import { AnimatePresence, motion } from "motion/react";
import {
  lazy,
  Suspense,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { SqlCode } from "./SqlCode";
import { formatSqlCell } from "@/lib/sql-cell-format";
import {
  Activity,
  AlertTriangle,
  Check,
  ChevronRight,
  Copy,
  DatabaseZap,
  Lightbulb,
  Maximize2,
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

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
  // A genuine analytical answer (has data/metrics) gets the editorial "Özet"
  // eyebrow + hairline; greetings, clarifications, and out-of-scope guidance
  // stay plain so the eyebrow never mislabels a non-report reply.
  const isDataAnswer = Boolean(message.sqlResult) || (message.metricCards?.length ?? 0) > 0;
  const resultDisplayMode =
    message.visibleSections?.includes("chart") && !message.visibleSections.includes("table")
      ? "chart"
      : message.visibleSections?.includes("chart") && message.visibleSections.includes("table")
        ? "both"
        : "table";
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

  // Copy the *visible artifact*, not just message.content. For a table/chart
  // answer, message.content is often only a scope note ("Önceki cevaptaki
  // kapsam kullanıldı.") — the meaningful output is the table. For a SQL-only
  // answer the artifact is the query itself.
  const buildCopyText = () => {
    const content = message.content?.trim() ?? "";
    const sections = message.visibleSections;
    const result = message.sqlResult;
    const isSqlOnly =
      message.responseMode === "sql" ||
      Boolean(
        sections?.includes("sql") &&
          !sections.includes("table") &&
          !sections.includes("chart"),
      );
    if (isSqlOnly && result?.query?.trim()) {
      return result.query.trim();
    }
    const parts: string[] = [];
    if (content) parts.push(content);
    if (result && result.columns.length > 0 && result.rows.length > 0) {
      const header = result.columns.join("\t");
      const body = result.rows
        .map((row) =>
          result.columns
            .map((column) => {
              const cell = formatSqlCell(column, row[column]);
              return cell.kind === "null" ? "" : cell.display;
            })
            .join("\t"),
        )
        .join("\n");
      parts.push(`${header}\n${body}`);
    }
    return parts.join("\n\n").trim() || content;
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(buildCopyText());
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
          ) : message.responseMode === "sql" ? (
            <AssistantSqlText sql={message.content} />
          ) : isDataAnswer ? (
            <div>
              <span className="mb-1.5 inline-flex items-center gap-2 text-[10.5px] font-bold uppercase tracking-[0.08em] text-cyan before:h-[2px] before:w-3.5 before:rounded-full before:bg-cyan before:content-['']">
                {tr.chat.summaryEyebrow}
              </span>
              <AssistantText content={message.content} animate={animateResponse} />
              <div className="mt-2.5 h-px bg-border" />
            </div>
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
                    className="glass relative flex min-h-[104px] min-w-0 flex-col overflow-hidden rounded-xl border border-border/60 py-3 pl-4 pr-3.5 transition-shadow hover:shadow-[var(--shadow-soft,0_8px_24px_-12px_rgba(23,32,51,.14))]"
                  >
                    <span
                      aria-hidden
                      className="absolute inset-y-0 left-0 w-[3px] bg-gradient-to-b from-primary to-cyan"
                    />
                    <div
                      className={cn(
                        // NOT `[overflow-wrap:anywhere]` here: that breaks a
                        // figure mid-digits ("1.241.5 / 38…"), which is
                        // unreadable and can even be misread as a different
                        // number. The value wraps at spaces only ("1.241.538"
                        // / "randevu") and shrinks a step earlier so a
                        // thousands-separated figure still fits one line.
                        "line-clamp-2 min-h-10 overflow-hidden font-semibold tabular-nums tracking-tight",
                        valueLength > 24
                          ? "text-xs leading-5"
                          : valueLength > 12
                            ? "text-sm leading-5"
                            : "text-xl leading-6",
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
        {!isUser &&
          message.showSqlTable &&
          message.sqlResult &&
          message.showResultInline &&
          !message.streaming && (
            <div className="w-full">
              <Suspense fallback={<div className="h-24 animate-pulse rounded-lg bg-muted/40" />}>
                <LazySqlResultsTable data={message.sqlResult} displayMode={resultDisplayMode} />
              </Suspense>
            </div>
          )}
        {!isUser &&
          message.showSqlTable &&
          message.sqlResult &&
          !message.showResultInline &&
          !message.streaming && (
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
                        <LazySqlResultsTable
                          data={message.sqlResult}
                          displayMode={resultDisplayMode}
                        />
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

function CodeCopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error(tr.common.copyFailed);
    }
  };

  return (
    <button
      type="button"
      onClick={copy}
      aria-label={tr.common.copy}
      className="absolute right-2 top-2 flex items-center gap-1 rounded-md border border-border/60 bg-background/80 px-2 py-1 text-[11px] text-muted-foreground backdrop-blur transition hover:bg-accent hover:text-foreground"
    >
      {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
      {copied ? tr.common.copied : tr.common.copy}
    </button>
  );
}

function AssistantSqlText({ sql }: { sql: string }) {
  return <SqlCode sql={sql} />;
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
  const reportMarkdown = streaming ? null : extractReportSections(animatedContent);
  const markdownContent = reportMarkdown?.mainMarkdown ?? animatedContent;

  return (
    <div className="prose-chat">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ className, children, ...props }) {
            const isBlock = className?.includes("language-");
            if (isBlock) {
              const codeText = String(children).replace(/\n$/, "");
              // A SQL fence gets the branded, syntax-highlighted block; any
              // other language keeps the plain copy-able pre.
              if (className?.includes("language-sql")) {
                return <SqlCode sql={codeText} />;
              }
              return (
                <div className="relative my-2">
                  <pre className="overflow-x-auto rounded-lg border border-border bg-muted p-3 pr-20 text-xs text-foreground">
                    <code {...props}>{children}</code>
                  </pre>
                  <CodeCopyButton text={codeText} />
                </div>
              );
            }
            return (
              <code
                className="rounded border border-border/60 bg-muted px-1.5 py-0.5 text-xs text-foreground"
                {...props}
              >
                {children}
              </code>
            );
          },
          table({ children }) {
            return <MarkdownTable>{children}</MarkdownTable>;
          },
          th({ children }) {
            return (
              <th className="min-w-28 border-b border-border bg-muted px-3 py-2 text-left align-top text-[11px] font-semibold uppercase tracking-wide text-muted-foreground [overflow-wrap:anywhere]">
                {children}
              </th>
            );
          },
          td({ children }) {
            const numeric = isNumericCell(children);
            return (
              <td
                className={cn(
                  "min-w-28 border-b border-border/50 px-3 py-2 align-top [overflow-wrap:anywhere]",
                  numeric && "text-right tabular-nums",
                )}
              >
                {children}
              </td>
            );
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
        {markdownContent}
      </ReactMarkdown>
      {reportMarkdown && reportMarkdown.sections.length > 0 && (
        <ReportSections sections={reportMarkdown.sections} />
      )}
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

function MarkdownTable({ children }: { children: ReactNode }) {
  const [expanded, setExpanded] = useState(false);
  const [overflowing, setOverflowing] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // A report table wider than the chat column can only be read by
  // horizontal scrolling inside a cramped box — so when it overflows we make
  // the fullscreen affordance obvious (button always shown, whole table
  // clickable) instead of the quiet hover-only reveal used for tables that
  // already fit.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const measure = () => setOverflowing(el.scrollWidth - el.clientWidth > 1);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [children]);

  const renderTable = () => <table className="min-w-max table-auto text-xs">{children}</table>;

  return (
    <>
      <div className="group/table relative my-2 w-fit max-w-full overflow-hidden rounded-xl border border-border [&_tbody_tr:hover]:bg-primary/5 [&_tbody_tr:nth-child(even)]:bg-muted/30">
        <button
          type="button"
          onClick={() => setExpanded(true)}
          aria-label={tr.sqlTable.openFullscreen}
          title={tr.sqlTable.openFullscreen}
          className={cn(
            "absolute right-2 top-2 z-10 grid h-7 w-7 place-items-center rounded-md border border-border/70 bg-background/85 text-muted-foreground shadow-sm backdrop-blur transition hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60",
            overflowing
              ? "opacity-100"
              : "opacity-100 sm:opacity-0 sm:group-hover/table:opacity-100 sm:group-focus-within/table:opacity-100",
          )}
        >
          <Maximize2 className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
        <div
          ref={scrollRef}
          className={cn("max-w-full overflow-x-auto", overflowing && "cursor-zoom-in")}
          {...(overflowing
            ? {
                role: "button" as const,
                tabIndex: 0,
                "aria-label": tr.sqlTable.openFullscreen,
                onClick: () => setExpanded(true),
                onKeyDown: (event: ReactKeyboardEvent) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    setExpanded(true);
                  }
                },
              }
            : {})}
        >
          {renderTable()}
        </div>
      </div>
      <Dialog open={expanded} onOpenChange={setExpanded}>
        <DialogContent className="h-[calc(100vh-3rem)] w-[min(calc(100vw-2rem),72rem)] max-w-none gap-0 overflow-hidden p-0">
          <DialogHeader className="shrink-0 border-b border-border px-5 py-4">
            <DialogTitle className="text-base">{tr.sqlTable.tableFullscreenTitle}</DialogTitle>
            <DialogDescription className="text-xs">
              {tr.sqlTable.tableFullscreenDescription}
            </DialogDescription>
          </DialogHeader>
          <div className="min-h-0 overflow-auto p-4">
            <div className="min-w-max overflow-hidden rounded-xl border border-border [&_tbody_tr:hover]:bg-primary/5 [&_tbody_tr:nth-child(even)]:bg-muted/30">
              {renderTable()}
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

type ReportSectionKind = "metrics" | "findings" | "assumptions";

type ReportSection = {
  kind: ReportSectionKind;
  title: string;
  items: string[];
};

type ParsedReportMarkdown = {
  mainMarkdown: string;
  sections: ReportSection[];
};

const reportSectionMarkers: Record<string, Omit<ReportSection, "items">> = {
  "**Sorgulanan metrikler**": {
    kind: "metrics",
    title: "Sorgulanan metrikler",
  },
  "**Öne çıkan bulgular**": {
    kind: "findings",
    title: "Öne çıkan bulgular",
  },
  "**Varsayımlar ve Sınırlamalar**": {
    kind: "assumptions",
    title: "Varsayımlar ve Sınırlamalar",
  },
};

function extractReportSections(markdown: string): ParsedReportMarkdown {
  const mainLines: string[] = [];
  const sections: ReportSection[] = [];
  let currentSection: ReportSection | null = null;

  markdown.split(/\r?\n/).forEach((line) => {
    const trimmed = line.trim();
    const marker = reportSectionMarkers[trimmed];

    if (marker) {
      if (currentSection) {
        sections.push(currentSection);
      }
      currentSection = { ...marker, items: [] };
      return;
    }

    if (!currentSection) {
      mainLines.push(line);
      return;
    }

    const bulletMatch = trimmed.match(/^[-*]\s+(.+)$/);
    if (bulletMatch) {
      currentSection.items.push(bulletMatch[1].trim());
      return;
    }

    if (!trimmed) {
      return;
    }

    if (currentSection.items.length === 0) {
      currentSection.items.push(trimmed);
      return;
    }

    currentSection.items[currentSection.items.length - 1] += ` ${trimmed}`;
  });

  if (currentSection) {
    sections.push(currentSection);
  }

  return {
    mainMarkdown: mainLines.join("\n").trimEnd(),
    sections: sections.filter((section) => section.items.length > 0),
  };
}

function ReportSections({ sections }: { sections: ReportSection[] }) {
  return (
    <div className="mt-4 grid gap-3" data-report-sections>
      {sections.map((section) => {
        const Icon =
          section.kind === "metrics"
            ? Activity
            : section.kind === "assumptions"
              ? AlertTriangle
              : Lightbulb;
        return (
          <section key={section.kind} data-report-section={section.kind}>
            <div className="mb-2 flex items-center gap-2">
              <span className="grid h-6 w-6 shrink-0 place-items-center rounded-md border border-border/70 bg-background/50 text-primary">
                <Icon className="h-3.5 w-3.5" aria-hidden="true" />
              </span>
              <h2 className="text-sm font-semibold leading-6 text-foreground">{section.title}</h2>
            </div>
            <div className="grid gap-2">
              {section.items.map((item, index) =>
                section.kind === "metrics" ? (
                  <MetricSummaryItem item={item} key={`${section.kind}-${index}`} />
                ) : (
                  <FindingSummaryItem item={item} key={`${section.kind}-${index}`} />
                ),
              )}
            </div>
          </section>
        );
      })}
    </div>
  );
}

function MetricSummaryItem({ item }: { item: string }) {
  const parsed = parseMetricItem(item);

  return (
    <div
      className="rounded-lg border border-border/70 bg-background/45 px-3 py-2.5 shadow-sm shadow-black/[0.02]"
      data-report-section-item="metric"
    >
      <div className="text-sm font-semibold leading-5 text-foreground">{parsed.label}</div>
      {parsed.parts.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {parsed.parts.map((part) => (
            <span
              key={part}
              className="rounded-md border border-border/60 bg-muted/35 px-2 py-1 text-[11px] font-medium leading-4 text-muted-foreground"
            >
              {part}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function FindingSummaryItem({ item }: { item: string }) {
  return (
    <div
      className="rounded-lg border border-primary/20 bg-primary/5 px-3 py-2.5"
      data-report-section-item="finding"
    >
      <p className="text-sm leading-relaxed text-foreground">{stripInlineMarkdown(item)}</p>
    </div>
  );
}

function parseMetricItem(item: string): { label: string; parts: string[] } {
  const normalized = stripInlineMarkdown(item);
  const match = normalized.match(/^([^:]+):\s*(.*)$/);

  if (!match) {
    return { label: normalized, parts: [] };
  }

  return {
    label: match[1].trim(),
    parts: match[2]
      .split(",")
      .map((part) => part.trim())
      .filter(Boolean),
  };
}

function stripInlineMarkdown(value: string): string {
  return value.replace(/\*\*(.*?)\*\*/g, "$1").trim();
}

function nodeToText(node: ReactNode): string {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(nodeToText).join("");
  if (typeof node === "object" && "props" in node) {
    return nodeToText((node as { props?: { children?: ReactNode } }).props?.children);
  }
  return "";
}

// A report-table cell whose text is purely a number (Türkçe "25.464",
// "%71,4", "-1.196") — such columns are right-aligned with tabular figures.
function isNumericCell(children: ReactNode): boolean {
  const text = nodeToText(children).trim();
  if (!text) return false;
  return /^[-+]?[%₺$]?\s?\d[\d.,\s]*%?$/.test(text);
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
