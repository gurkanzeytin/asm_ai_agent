import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import type { Conversation, Message } from "@/components/asm/types";
import type { SqlResult } from "@/components/asm/SqlResultsTable";
import { ApiError, generateReport } from "@/lib/api";
import { buildMetricCards } from "@/lib/presentation";
import { tr } from "@/locales/tr";

const INITIAL_CONVERSATION: Conversation = {
  id: "initial-conversation",
  title: tr.header.newConversation,
  messages: [],
  updatedAt: 0,
};

function makeId() {
  return globalThis.crypto?.randomUUID() ?? Math.random().toString(36).slice(2, 10);
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

  useEffect(
    () => () => {
      activeRequestRef.current?.controller.abort();
      if (animationTimerRef.current !== null) window.clearTimeout(animationTimerRef.current);
    },
    [],
  );

  const active = conversations.find((conversation) => conversation.id === activeId) ?? null;
  const messages = active?.messages ?? [];
  const lastMetadata = [...messages].reverse().find((message) => message.metadata)?.metadata;
  const lastSql =
    [...messages].reverse().find((message) => message.sqlResult)?.sqlResult?.query ?? null;

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
      const response = await generateReport(content, conversationId, controller.signal);
      const queryResult = response.query_result;
      const sqlResult: SqlResult | undefined = queryResult
        ? {
            columns: queryResult.columns,
            rows: queryResult.rows,
            query: response.generated_sql ?? undefined,
            durationMs: response.timing?.execute_sql_ms ?? undefined,
            visualization:
              response.visualization?.type ?? response.analytics?.visualization?.type ?? null,
          }
        : undefined;
      const responseContent =
        response.report?.markdown?.trim() ||
        (response.success ? tr.chat.noReport : tr.chat.requestFailedFallback);
      const workflowDurationMs = response.timing?.total_ms;
      const latencyMs =
        workflowDurationMs != null && workflowDurationMs > 0
          ? workflowDurationMs
          : (response.metadata?.latency_ms ?? 0);
      const model = response.metadata?.model ?? "-";

      updateConversation(conversationId, (conversation) => ({
        ...conversation,
        messages: conversation.messages.map((message) =>
          message.id === assistantId
            ? {
                ...message,
                content: responseContent,
                streaming: false,
                status: "success",
                sqlResult,
                showSqlTable: Boolean(sqlResult),
                metricCards: queryResult
                  ? buildMetricCards(queryResult.columns, queryResult.rows)
                  : [],
                metadata: {
                  model,
                  latencyMs,
                  tokens:
                    (response.metadata?.prompt_tokens ?? 0) +
                    (response.metadata?.completion_tokens ?? 0),
                },
              }
            : message,
        ),
      }));

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

      const message = error instanceof ApiError ? error.message : tr.chat.unexpectedError;
      updateConversation(conversationId, (conversation) => ({
        ...conversation,
        messages: conversation.messages.map((item) =>
          item.id === assistantId
            ? { ...item, content: message, streaming: false, status: "error" }
            : item,
        ),
      }));
      toast.error(tr.chat.requestFailed, { description: message });
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
