import type { ReportResponse } from "@/lib/api";

export type ResponseMode = "answer" | "sql" | "data" | "visualization";
export type VisibleSection = "answer" | "sql" | "table" | "metrics" | "chart";

const TERMINAL_ANSWER_OUTCOMES = new Set([
  "OUT_OF_SCOPE",
  "ASK_CLARIFICATION",
  "NO_RESULT_GUIDANCE",
  "SAFE_ERROR",
]);

const SQL_MARKER = /\b(sql|sorgu|sorgusunu|sorguyu)\b/;
const SQL_ONLY_MARKER =
  /\b(sadece|yalniz)\b.{0,30}\b(sql|sorgu|sorgusunu|sorguyu)\b|\b(sql|sorgu|sorgusunu|sorguyu)\b.{0,40}\b(ver|yaz|uret|olustur|goster)\b|\bcalistirma\b/;
const DATA_MARKER = /\b(veri\w*|kayit\w*|liste\w*|getir\w*|cek\w*|tablo\w*|sonuc\w*)\b/;
const EXECUTION_MARKER = /\b(calistir\w*|cek\w*|getir\w*|listele\w*|sonuc\w*)\b/;
const VISUAL_MARKER =
  /\b(grafik\w*|grafig\w*|chart|gorsel\w*|ciz\w*|cizgi\w*|bar|sutun\w*|pasta|oranlama)\b/;

function foldTurkish(text: string): string {
  return text
    .replace(/İ/g, "i")
    .replace(/I/g, "i")
    .replace(/ı/g, "i")
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "");
}

function backendMode(response: ReportResponse): ResponseMode | null {
  const mode = response.response_mode;
  return mode === "answer" || mode === "sql" || mode === "data" || mode === "visualization"
    ? mode
    : null;
}

export function inferResponseMode(question: string, response: ReportResponse): ResponseMode {
  if (TERMINAL_ANSWER_OUTCOMES.has(response.outcome ?? "")) return "answer";
  const supplied = backendMode(response);
  if (supplied) return supplied;

  const folded = foldTurkish(question);
  if (VISUAL_MARKER.test(folded)) return "visualization";
  const hasDataMarker = DATA_MARKER.test(folded);
  if (SQL_ONLY_MARKER.test(folded) && !(hasDataMarker || EXECUTION_MARKER.test(folded))) {
    return "sql";
  }
  if (hasDataMarker || (SQL_MARKER.test(folded) && EXECUTION_MARKER.test(folded))) {
    return "data";
  }
  return "answer";
}

export function visibleSections(response: ReportResponse): VisibleSection[] {
  const allowed = new Set<VisibleSection>(["answer", "sql", "table", "metrics", "chart"]);
  return (response.visible_sections ?? []).filter((section): section is VisibleSection =>
    allowed.has(section as VisibleSection),
  );
}

export function shouldShowAnswerText(response: ReportResponse, mode: ResponseMode): boolean {
  const sections = visibleSections(response);
  if (sections.length > 0) return sections.includes("answer") || sections.includes("sql");
  return mode === "answer" || mode === "sql";
}

export function buildResponseContent(response: ReportResponse, mode: ResponseMode): string {
  if (mode === "sql" || visibleSections(response).includes("sql")) {
    return response.generated_sql?.trim() ?? "Bu soru icin SQL sorgusu uretilemedi.";
  }
  if (!shouldShowAnswerText(response, mode)) return "";
  return response.report?.markdown?.trim() ?? "";
}
