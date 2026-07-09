export interface TimingData {
  retrieve_context_ms: number | null;
  generate_sql_ms: number | null;
  validate_sql_ms: number | null;
  execute_sql_ms: number | null;
  generate_report_ms: number | null;
  llm_total_ms: number | null;
  total_ms: number;
}

export interface ReportResponse {
  success: boolean;
  workflow_id: string;
  question: string;
  generated_sql: string;
  query_result: {
    columns: string[];
    rows: Record<string, unknown>[];
    row_count: number;
  };
  report: {
    title: string;
    markdown: string;
  };
  metadata: {
    provider: string;
    model: string;
    latency_ms: number;
    prompt_tokens: number | null;
    completion_tokens: number | null;
  };
  timing?: TimingData;
}
