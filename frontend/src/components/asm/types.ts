import type { SqlResult } from "./SqlResultsTable";
import type { MetricCard } from "@/lib/presentation";
import type { WorkflowStage } from "@/lib/api";
import type { ResponseMode } from "@/lib/output-intent";

export type Role = "user" | "assistant";
export type MessageStatus = "success" | "error" | "stopped";
export type MessageErrorKind = "network" | "query" | "server" | "invalid";

export interface Message {
  id: string;
  role: Role;
  content: string;
  createdAt: number;
  streaming?: boolean;
  progressStage?: WorkflowStage;
  status?: MessageStatus;
  errorKind?: MessageErrorKind;
  errorCode?: string;
  outcome?: string;
  rowCount?: number;
  prompt?: string;
  sqlResult?: SqlResult;
  responseMode?: ResponseMode;
  visibleSections?: string[];
  /** SQL gerçekten çalıştıysa ham sonuç tablosu gösterilir (AI-011 §8). */
  showSqlTable?: boolean;
  showResultInline?: boolean;
  /** Tek satırlık typed özetlerden türetilen Türkçe metrik kartları. */
  metricCards?: MetricCard[];
  /** Backend'den dönen gerçek yanıt metadata'sı (model, süre, token). */
  metadata?: {
    model: string;
    latencyMs: number;
    tokens: number;
  };
}

export interface Conversation {
  id: string;
  title: string;
  messages: Message[];
  favorite?: boolean;
  updatedAt: number;
}
