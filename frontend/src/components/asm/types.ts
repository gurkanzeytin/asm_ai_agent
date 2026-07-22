import type { SqlResult } from "./SqlResultsTable";
import type { MetricCard } from "@/lib/presentation";

export type Role = "user" | "assistant";
export type MessageStatus = "success" | "error" | "stopped";

export interface Message {
  id: string;
  role: Role;
  content: string;
  createdAt: number;
  streaming?: boolean;
  status?: MessageStatus;
  prompt?: string;
  sqlResult?: SqlResult;
  /** SQL gerçekten çalıştıysa ham sonuç tablosu gösterilir (AI-011 §8). */
  showSqlTable?: boolean;
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
