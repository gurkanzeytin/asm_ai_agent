import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import type {
  Conversation,
  Message,
  MessageErrorKind,
  MessageStatus,
} from "@/components/asm/types";
import type { SqlResult } from "@/components/asm/SqlResultsTable";
import {
  ApiError,
  generateReportStream,
  type DisplayableKpiPayload,
  type QueryResultPayload,
  type ReportResponse,
  type WorkflowStage,
} from "@/lib/api";
import {
  buildAnalyticsCards,
  buildMetricCards,
  formatValueTr,
  type MetricCard,
} from "@/lib/presentation";
import {
  buildResponseContent,
  inferResponseMode,
  visibleSections,
  type ResponseMode,
} from "@/lib/output-intent";
import { tr } from "@/locales/tr";
import { MAX_UI_ROWS_PER_PAGE } from "@/lib/result-limits";
import { traceChatRuntime } from "@/lib/chat-runtime-trace";

const TABLE_HIDDEN_OUTCOMES = new Set([
  "OUT_OF_SCOPE",
  "ASK_CLARIFICATION",
  "NO_RESULT_GUIDANCE",
  "SAFE_ERROR",
]);
const SCALAR_RESULT_SHAPES = new Set(["scalar_aggregate", "multi_metric_scalar_aggregate"]);

export function shouldShowSqlTable(
  response: ReportResponse,
  sqlResult: SqlResult | undefined,
  responseMode: ResponseMode = "answer",
): boolean {
  if (!sqlResult || TABLE_HIDDEN_OUTCOMES.has(response.outcome ?? "")) return false;
  const sections = visibleSections(response);
  if (sections.length > 0) return sections.includes("table") || sections.includes("chart");
  if (responseMode === "sql") return false;
  if (responseMode === "data") return sqlResult.columns.length > 0;
  if (responseMode === "visualization") {
    return (
      Boolean(sqlResult.visualization) ||
      !SCALAR_RESULT_SHAPES.has(response.analytics?.result_shape ?? "")
    );
  }
  return !SCALAR_RESULT_SHAPES.has(response.analytics?.result_shape ?? "");
}

/**
 * "Temel Göstergeler" cards (AI-INTELLIGENCE-014). Prefers the deterministic
 * analytics engine's KPI dict (total/average/median/trend/...) whenever it
 * carries usable scalar metrics — this is the richer, always-Türkçe-labeled
 * source and is what actually populates for TIME_SERIES/CATEGORICAL (multi-
 * row) results. Falls back to the raw single-row query_result heuristic
 * (buildMetricCards) only when analytics has nothing to show.
 */
function buildKeyMetricCards(
  response: ReportResponse,
  queryResult: QueryResultPayload | null | undefined,
): MetricCard[] {
  const displayable = response.analytics?.displayable_kpis;
  if (displayable?.length) return displayable.map(buildDisplayableKpiCard);

  const resultShape = response.analytics?.result_shape;
  if (resultShape === "scalar_aggregate" || resultShape === "multi_metric_scalar_aggregate") {
    return queryResult ? buildMetricCards(queryResult.columns, queryResult.rows) : [];
  }
  const analyticsCards = buildAnalyticsCards(response.analytics?.metrics, {
    resolvedMetrics: response.resolved_metrics,
    limit: 8,
  });
  if (analyticsCards.length > 0) return analyticsCards;
  return queryResult ? buildMetricCards(queryResult.columns, queryResult.rows) : [];
}

function buildDisplayableKpiCard(item: DisplayableKpiPayload): MetricCard {
  if (item.value == null) return { label: item.label, value: tr.common.noData, isEmpty: true };
  if (typeof item.value === "number") {
    return { label: item.label, value: formatValueTr(item.key, item.value) };
  }
  return { label: item.label, value: String(item.value) };
}

const INITIAL_CONVERSATION: Conversation = {
  id: "initial-conversation",
  title: tr.header.newConversation,
  messages: [],
  updatedAt: 0,
};
const EMPTY_MESSAGES: Message[] = [];

function makeId() {
  return globalThis.crypto?.randomUUID() ?? Math.random().toString(36).slice(2, 10);
}

function classifyError(error: unknown): { kind: MessageErrorKind; code: string } {
  if (!(error instanceof ApiError)) return { kind: "server", code: "UNKNOWN_ERROR" };
  if (error.code === "NETWORK_ERROR") return { kind: "network", code: error.code };
  if (error.code === "INVALID_RESPONSE") return { kind: "invalid", code: error.code };
  if (
    error.code === "QUERY_EXECUTION_ERROR" ||
    error.code === "SQL_VALIDATION_ERROR" ||
    error.code === "SQL_GENERATION_ERROR"
  ) {
    return { kind: "query", code: error.code };
  }
  return { kind: "server", code: error.code };
}

interface ActiveRequest {
  assistantId: string;
  conversationId: string;
  controller: AbortController;
}

export function useChatController() {
  const [conversations, setConversations] = useState<Conversation[]>([INITIAL_CONVERSATION]);
  const [activeId, setActiveId] = useState<string | null>(INITIAL_CONVERSATION.id);
  const [input, setInput] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [animatedMessageId, setAnimatedMessageId] = useState<string | null>(null);
  const activeRequestRef = useRef<ActiveRequest | null>(null);
  const animationTimerRef = useRef<number | null>(null);
  const activeIdRef = useRef(activeId);
  const conversationsRef = useRef(conversations);
  const terminalAssistantIdsRef = useRef(new Set<string>());

  activeIdRef.current = activeId;
  conversationsRef.current = conversations;

  useEffect(
    () => () => {
      activeRequestRef.current?.controller.abort();
      if (animationTimerRef.current !== null) window.clearTimeout(animationTimerRef.current);
    },
    [],
  );

  const active = conversations.find((conversation) => conversation.id === activeId) ?? null;
  const messages = active?.messages ?? EMPTY_MESSAGES;
  const lastMetadata = [...messages].reverse().find((message) => message.metadata)?.metadata;
  const lastSql =
    [...messages].reverse().find((message) => message.sqlResult)?.sqlResult?.query ?? null;

  useEffect(() => {
    traceChatRuntime("state-committed", {
      activeConversationId: activeId,
      visibleMessageIds: messages.map((message) => message.id),
      visibleAssistantContentLengths: messages
        .filter((message) => message.role === "assistant")
        .map((message) => ({ id: message.id, contentLength: message.content.length })),
    });
  }, [activeId, messages]);

  const updateConversation = (id: string, update: (conversation: Conversation) => Conversation) => {
    setConversations((list) =>
      list.map((conversation) => (conversation.id === id ? update(conversation) : conversation)),
    );
  };

  const stopRequestForConversation = (conversationId: string) => {
    if (activeRequestRef.current?.conversationId === conversationId) {
      activeRequestRef.current.controller.abort();
    }
  };

  const send = async (text?: string) => {
    const content = (text ?? input).trim();
    if (!content || isGenerating) return;

    let conversationId = activeId;
    if (!conversationId) {
      conversationId = makeId();
      const conversation: Conversation = {
        id: conversationId,
        title: content.slice(0, 40),
        messages: [],
        updatedAt: Date.now(),
      };
      setConversations((list) => [conversation, ...list]);
      setActiveId(conversationId);
    }

    const userMessage: Message = {
      id: makeId(),
      role: "user",
      content,
      createdAt: Date.now(),
    };
    const assistantId = makeId();

    updateConversation(conversationId, (conversation) => ({
      ...conversation,
      title: conversation.messages.length === 0 ? content.slice(0, 40) : conversation.title,
      messages: [
        ...conversation.messages,
        userMessage,
        {
          id: assistantId,
          role: "assistant",
          content: "",
          createdAt: Date.now(),
          streaming: true,
          prompt: content,
        },
      ],
      updatedAt: Date.now(),
    }));
    setInput("");
    setIsGenerating(true);

    const controller = new AbortController();
    activeRequestRef.current = { assistantId, conversationId, controller };

    try {
      const onProgress = (stage: WorkflowStage) => {
        updateConversation(conversationId, (conversation) => ({
          ...conversation,
          messages: conversation.messages.map((message) =>
            message.id === assistantId &&
            message.streaming &&
            !terminalAssistantIdsRef.current.has(assistantId)
              ? { ...message, progressStage: stage }
              : message,
          ),
        }));
      };
      const response = await generateReportStream(
        content,
        conversationId,
        onProgress,
        controller.signal,
      );
      const responseMode = inferResponseMode(content, response);
      const sections = visibleSections(response);
      const queryResult = response.query_result;
      const backendRowCount = queryResult?.rows.length ?? 0;
      const boundedQueryResult = queryResult
        ? { ...queryResult, rows: queryResult.rows.slice(0, MAX_UI_ROWS_PER_PAGE) }
        : undefined;
      const sqlResult: SqlResult | undefined = boundedQueryResult
        ? {
            columns: boundedQueryResult.columns,
            rows: boundedQueryResult.rows,
            columnMetadata: boundedQueryResult.column_metadata,
            resolvedMetrics: response.resolved_metrics,
            resolvedDimensions: response.resolved_dimensions,
            query: response.generated_sql ?? undefined,
            durationMs: response.timing?.execute_sql_ms ?? undefined,
            visualization:
              response.visualization?.type ?? response.analytics?.visualization?.type ?? null,
            technicalRowCount:
              response.analytics?.technical_row_count ?? boundedQueryResult.row_count,
            resultShape: response.analytics?.result_shape,
            sourceRecordCount: boundedQueryResult.source_record_count,
            resultGroupCount: boundedQueryResult.result_group_count,
            returnedRowCount: boundedQueryResult.returned_row_count,
            displayedRowCount: boundedQueryResult.displayed_row_count,
            resultTruncated:
              Boolean(boundedQueryResult.result_truncated) ||
              backendRowCount > MAX_UI_ROWS_PER_PAGE,
            hasMore: Boolean(boundedQueryResult.has_more) || backendRowCount > MAX_UI_ROWS_PER_PAGE,
            totalCount: boundedQueryResult.total_count,
            appliedLimit: boundedQueryResult.applied_limit,
          }
        : undefined;
      const modeContent = buildResponseContent(response, responseMode);
      const suppressText =
        response.success &&
        sections.length > 0 &&
        !sections.includes("answer") &&
        !sections.includes("sql");
      const responseContent =
        modeContent ||
        (suppressText ? "" : response.success ? tr.chat.noReport : tr.chat.requestFailedFallback);
      const hasControlledReport = Boolean(response.report?.markdown?.trim());
      const workflowDurationMs = response.timing?.total_ms;
      const latencyMs =
        workflowDurationMs != null && workflowDurationMs > 0
          ? workflowDurationMs
          : (response.metadata?.latency_ms ?? 0);
      const model = response.metadata?.model ?? "-";

      const currentConversation = conversationsRef.current.find(
        (conversation) => conversation.id === conversationId,
      );
      traceChatRuntime("before-completion-update", {
        targetConversationId: conversationId,
        activeConversationId: activeIdRef.current,
        placeholderAssistantMessageId: assistantId,
        currentMessageIds: currentConversation?.messages.map((message) => message.id) ?? [],
      });

      const isSuccessful = response.success || hasControlledReport;
      const messageStatus: MessageStatus = isSuccessful ? "success" : "error";
      const messageErrorKind: MessageErrorKind | undefined = isSuccessful ? undefined : "server";
      const messageErrorCode: string | undefined = isSuccessful
        ? undefined
        : (response.outcome ?? "WORKFLOW_ERROR");

      terminalAssistantIdsRef.current.add(assistantId);
      updateConversation(conversationId, (conversation) => {
        const target = conversation.messages.find((message) => message.id === assistantId);
        const nextMessages = conversation.messages.map((message) =>
          message.id === assistantId
            ? {
                ...message,
                content: responseContent,
                streaming: false,
                progressStage: undefined,
                status: messageStatus,
                errorKind: messageErrorKind,
                errorCode: messageErrorCode,
                outcome: response.outcome ?? undefined,
                rowCount: boundedQueryResult?.row_count,
                sqlResult,
                responseMode,
                visibleSections: sections,
                showSqlTable: shouldShowSqlTable(response, sqlResult, responseMode),
                showResultInline:
                  sections.length > 0
                    ? sections.includes("table") || sections.includes("chart")
                    : responseMode === "data" || responseMode === "visualization",
                metricCards:
                  responseMode === "sql" ||
                  responseMode === "data" ||
                  (sections.length > 0 && !sections.includes("metrics"))
                    ? []
                    : buildKeyMetricCards(response, boundedQueryResult),
                metadata: {
                  model,
                  latencyMs,
                  tokens:
                    (response.metadata?.prompt_tokens ?? 0) +
                    (response.metadata?.completion_tokens ?? 0),
                },
              }
            : message,
        );
        traceChatRuntime("completion-updater", {
          targetAssistantFound: Boolean(target),
          oldContent: target?.content ?? null,
          newContent: responseContent,
          resultingMessages: nextMessages.map((message) => ({
            id: message.id,
            role: message.role,
            content: message.content,
            streaming: message.streaming ?? false,
          })),
        });
        return { ...conversation, messages: nextMessages };
      });

      setAnimatedMessageId(assistantId);
      if (animationTimerRef.current !== null) window.clearTimeout(animationTimerRef.current);
      animationTimerRef.current = window.setTimeout(() => setAnimatedMessageId(null), 1600);
      toast.success(tr.chat.responseReady, {
        description: tr.chat.responseReadyDescription((latencyMs / 1000).toFixed(2)),
        className: "response-ready-toast",
        duration: 2800,
      });
    } catch (error: unknown) {
      if (error instanceof DOMException && error.name === "AbortError") {
        updateConversation(conversationId, (conversation) => ({
          ...conversation,
          messages: conversation.messages.map((message) =>
            message.id === assistantId
              ? {
                  ...message,
                  content: tr.chat.generationStopped,
                  streaming: false,
                  status: "stopped",
                }
              : message,
          ),
        }));
        return;
      }

      const errorInfo = classifyError(error);
      const errorCopy = tr.chat.errors[errorInfo.kind];
      updateConversation(conversationId, (conversation) => ({
        ...conversation,
        messages: conversation.messages.map((item) =>
          item.id === assistantId
            ? {
                ...item,
                content: errorCopy.description,
                streaming: false,
                progressStage: undefined,
                status: "error",
                errorKind: errorInfo.kind,
                errorCode: errorInfo.code,
              }
            : item,
        ),
      }));
      toast.error(errorCopy.title, { description: errorCopy.description });
    } finally {
      if (activeRequestRef.current?.assistantId === assistantId) {
        activeRequestRef.current = null;
        setIsGenerating(false);
      }
    }
  };

  const stop = () => {
    if (!activeRequestRef.current) return;
    activeRequestRef.current.controller.abort();
    toast.warning(tr.chat.generationStopped);
  };

  const newChat = () => {
    const conversation: Conversation = {
      id: makeId(),
      title: tr.sidebar.newChat,
      messages: [],
      updatedAt: Date.now(),
    };
    setConversations((list) => [conversation, ...list]);
    setActiveId(conversation.id);
  };

  const clearChat = () => {
    if (!activeId) return;
    stopRequestForConversation(activeId);
    updateConversation(activeId, (conversation) => ({ ...conversation, messages: [] }));
    toast.info(tr.chat.chatCleared);
  };

  const deleteConversation = (id: string) => {
    stopRequestForConversation(id);
    setConversations((list) => list.filter((conversation) => conversation.id !== id));
    if (activeId === id) setActiveId(null);
    toast.info(tr.chat.conversationDeleted);
  };

  const toggleFavorite = (id: string) => {
    updateConversation(id, (conversation) => ({
      ...conversation,
      favorite: !conversation.favorite,
    }));
  };

  return {
    active,
    activeId,
    animatedMessageId,
    conversations,
    input,
    isGenerating,
    lastSql,
    messages,
    metrics: {
      responseMs: lastMetadata?.latencyMs ?? 0,
    },
    clearChat,
    deleteConversation,
    newChat,
    selectConversation: setActiveId,
    send,
    setInput,
    stop,
    toggleFavorite,
  };
}
