/**
 * Typed client for the Hospital AI Agent backend.
 *
 * The backend exposes POST {API_V1}/report/ which runs the full workflow:
 * intent → schema retrieval → SQL generation/validation/execution →
 * analytics → insights → observations → narrative report.
 *
 * In development the Vite server proxies /api to the backend (see
 * vite.config.ts), so no CORS configuration is needed. Override with
 * VITE_API_BASE_URL for other deployments.
 */

const API_BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ?? "/api/v1";

export interface ColumnMetadataPayload {
  key: string;
  label: string;
  format: ColumnFormat;
  unit: string | null;
  hidden?: boolean;
}

export interface QueryResultPayload {
  columns: string[];
  rows: Array<Record<string, string | number | null>>;
  row_count: number;
  source_record_count?: number | null;
  result_group_count?: number | null;
  returned_row_count?: number;
  displayed_row_count?: number;
  result_truncated?: boolean;
  applied_limit?: number;
  has_more?: boolean;
  total_count?: number | null;
  column_metadata?: ColumnMetadataPayload[];
}

export interface ReportPayload {
  title?: string | null;
  markdown: string;
}

export interface MetadataPayload {
  provider: string;
  model: string;
  latency_ms: number;
  prompt_tokens?: number | null;
  completion_tokens?: number | null;
}

export interface TimingPayload {
  analyze_intent_ms?: number | null;
  analyze_results_ms?: number | null;
  generate_insights_ms?: number | null;
  generate_observations_ms?: number | null;
  retrieve_context_ms?: number | null;
  generate_sql_ms?: number | null;
  validate_sql_ms?: number | null;
  execute_sql_ms?: number | null;
  generate_report_ms?: number | null;
  llm_total_ms?: number | null;
  total_ms: number;
}

export interface VisualizationPayload {
  type: string;
  reason: string;
}

export interface AnalyticsPayload {
  analytics_type: string;
  intents: string[];
  data_shape: string;
  metrics: Record<string, unknown>;
  insights: Record<string, unknown>;
  visualization?: VisualizationPayload | null;
  row_count: number;
  technical_row_count?: number;
  business_record_count?: number | null;
  result_shape?: string;
  aggregate_result?: boolean;
  displayable_kpis?: DisplayableKpiPayload[];
  metric_summaries?: Record<string, unknown>;
  comparison_category_count?: number | null;
  comparison_sufficient?: boolean | null;
  comparison_limitation_reason?: string | null;
}

export interface DisplayableKpiPayload {
  key: string;
  label: string;
  value: string | number | null;
  format: string;
  unit?: string | null;
}

export interface InsightPayload {
  title: string;
  summary: string;
  highlights: string[];
  observations: string[];
  considerations: string[];
  rules: string[];
  confidence: string;
  llm_generated: boolean;
}

export interface ObservationItemPayload {
  rule: string;
  category: string;
  text: string;
  evidence: Record<string, unknown>;
}

export interface ObservationsPayload {
  observations: ObservationItemPayload[];
  confidence: string;
  llm_worded: boolean;
}

export interface ReportResponse {
  success: boolean;
  workflow_id?: string | null;
  question: string;
  response_mode?: "answer" | "sql" | "data" | "visualization" | null;
  visible_sections?: string[];
  raw_question?: string | null;
  resolved_question?: string | null;
  answerability_input_source?: string;
  answerability_signals?: string[];
  generated_sql?: string | null;
  query_result?: QueryResultPayload | null;
  report?: ReportPayload | null;
  metadata?: MetadataPayload | null;
  timing?: TimingPayload | null;
  intent?: Record<string, unknown> | null;
  analytics?: AnalyticsPayload | null;
  insights?: InsightPayload | null;
  observations?: ObservationsPayload | null;
  visualization?: VisualizationPayload | null;
  outcome?: string | null;
  pending_clarification_field?: string | null;
  resolved_metrics?: string[];
  resolved_dimensions?: string[];
}

export type WorkflowStage =
  | "understanding"
  | "preparing_sql"
  | "validating_sql"
  | "executing_sql"
  | "analyzing_data"
  | "reporting";

const rowValueSchema = z.union([z.string(), z.number(), z.null()]);
const reportResponseSchema = z
  .object({
    success: z.boolean(),
    question: z.string(),
    response_mode: z.enum(["answer", "sql", "data", "visualization"]).nullable().optional(),
    visible_sections: z.array(z.string()).optional(),
    generated_sql: z.string().nullable().optional(),
    query_result: z
      .object({
        columns: z.array(z.string()),
        rows: z.array(z.record(rowValueSchema)),
        row_count: z.number(),
        source_record_count: z.number().nullable().optional(),
        result_group_count: z.number().nullable().optional(),
        returned_row_count: z.number().optional(),
        displayed_row_count: z.number().optional(),
        result_truncated: z.boolean().optional(),
        applied_limit: z.number().optional(),
        has_more: z.boolean().optional(),
        total_count: z.number().nullable().optional(),
        column_metadata: z
          .array(
            z.object({
              key: z.string(),
              label: z.string(),
              format: z.string(),
              unit: z.string().nullable().optional(),
              hidden: z.boolean().optional(),
            }),
          )
          .optional(),
      })
      .nullable()
      .optional(),
    report: z
      .object({
        title: z.string().nullable().optional(),
        markdown: z.string(),
      })
      .nullable()
      .optional(),
    metadata: z
      .object({
        provider: z.string(),
        model: z.string(),
        latency_ms: z.number(),
        prompt_tokens: z.number().nullable().optional(),
        completion_tokens: z.number().nullable().optional(),
      })
      .nullable()
      .optional(),
    timing: z
      .object({
        total_ms: z.number(),
      })
      .passthrough()
      .nullable()
      .optional(),
  })
  .passthrough();

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
    public readonly code = "UNKNOWN_ERROR",
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function generateReport(
  question: string,
  sessionId: string,
  signal?: AbortSignal,
): Promise<ReportResponse> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/report/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, session_id: sessionId }),
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(
      "Sunucuya ulaşılamıyor. API sunucusunun çalıştığından emin olun (uvicorn app.main:app).",
    );
  }

  if (!response.ok) {
    throw await apiErrorFromResponse(response);
  }

  const payload: unknown = await response.json();
  const parsed = reportResponseSchema.safeParse(payload);
  if (!parsed.success) throw new ApiError(tr.errors.invalidApiResponse, response.status);
  return parsed.data as ReportResponse;
}

async function apiErrorFromResponse(response: Response): Promise<ApiError> {
  let detail = `Request failed with status ${response.status}.`;
  let code = `HTTP_${response.status}`;
  try {
    const body = (await response.json()) as {
      detail?: unknown;
      message?: unknown;
      error_code?: unknown;
    };
    if (typeof body.detail === "string") detail = body.detail;
    else if (typeof body.message === "string") detail = body.message;
    if (typeof body.error_code === "string") code = body.error_code;
  } catch {
    // Keep status-derived fallbacks when the server did not return JSON.
  }
  return new ApiError(detail, response.status, code);
}

export async function generateReportStream(
  question: string,
  sessionId: string,
  onProgress: (stage: WorkflowStage) => void,
  signal?: AbortSignal,
): Promise<ReportResponse> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/report/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/x-ndjson" },
      body: JSON.stringify({ question, session_id: sessionId }),
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError("Sunucuya ulaşılamıyor.", undefined, "NETWORK_ERROR");
  }

  if (response.status === 404) return generateReport(question, sessionId, signal);
  if (!response.ok) throw await apiErrorFromResponse(response);
  if (!response.body) {
    throw new ApiError(tr.errors.invalidApiResponse, response.status, "INVALID_RESPONSE");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let completed: ReportResponse | null = null;

  const consumeLine = (line: string) => {
    if (!line.trim()) return;
    let event: unknown;
    try {
      event = JSON.parse(line);
    } catch {
      throw new ApiError(tr.errors.invalidApiResponse, response.status, "INVALID_RESPONSE");
    }
    if (!event || typeof event !== "object" || !("type" in event)) return;
    const payload = event as Record<string, unknown>;
    if (payload.type === "progress" && typeof payload.stage === "string") {
      onProgress(payload.stage as WorkflowStage);
      return;
    }
    if (payload.type === "error") {
      throw new ApiError(
        typeof payload.message === "string" ? payload.message : tr.chat.unexpectedError,
        response.status,
        typeof payload.error_code === "string" ? payload.error_code : "WORKFLOW_ERROR",
      );
    }
    if (payload.type === "complete") {
      const parsed = reportResponseSchema.safeParse(payload.data);
      if (!parsed.success) {
        throw new ApiError(tr.errors.invalidApiResponse, response.status, "INVALID_RESPONSE");
      }
      completed = parsed.data as ReportResponse;
      traceChatRuntime("complete-parsed", {
        eventType: payload.type,
        workflowId: completed.workflow_id ?? null,
        sessionId:
          typeof (payload.data as Record<string, unknown>).session_id === "string"
            ? (payload.data as Record<string, unknown>).session_id
            : null,
        reportMarkdownLength: completed.report?.markdown?.length ?? 0,
      });
    }
  };

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    lines.forEach(consumeLine);
    if (done) break;
  }
  consumeLine(buffer);

  if (!completed) {
    throw new ApiError(tr.errors.invalidApiResponse, response.status, "INVALID_RESPONSE");
  }
  return completed;
}
import { z } from "zod";
import { tr } from "@/locales/tr";
import type { ColumnFormat } from "@/lib/presentation";
import { traceChatRuntime } from "@/lib/chat-runtime-trace";
