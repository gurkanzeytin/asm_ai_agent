/**
 * Merkezî Türkçe sunum yardımcıları (AI-INTELLIGENCE-011).
 *
 * Teknik metric alias'ları kullanıcıya asla ham hâliyle gösterilmez; etiketler
 * ve sayı biçimleri yalnız bu modülden gelir. Backend'deki
 * app/reporting/presentation.py sözlüğüyle eş tutulmalıdır.
 */
import { tr } from "@/locales/tr";

export const METRIC_LABELS_TR: Record<string, string> = {
  appointment_count: "Toplam Randevu",
  cohort_total_count: "Son Dakika Randevusu",
  completed_count: "Gerçekleşen Randevu",
  completed_rate: "Gerçekleşme Oranı",
  checked_in_count: "Giriş Yapılmış Randevu",
  checked_in_rate: "Giriş Yapılma Oranı",
  no_show_count: "Gelmeyen Randevu",
  no_show_rate: "Gelmeme Oranı",
  in_progress_count: "İşlemi Süren Randevu",
  in_progress_rate: "İşlemde Olanların Oranı",
  waiting_count: "Bekleyen Randevu",
  waiting_rate: "Bekleme Oranı",
  current_period_count: "Mevcut Dönem Randevu Sayısı",
  baseline_period_count: "Önceki Dönem Randevu Sayısı",
  current_period_label: "Mevcut Dönem",
  baseline_period_label: "Önceki Dönem",
  absolute_change: "Sayısal Değişim",
  percentage_change: "Yüzdesel Değişim",
  rate_point_change: "Oran Farkı",
  unique_patient_count: "Tekil Hasta Sayısı",
  unique_doctor_count: "Tekil Doktor Sayısı",
  comparison_total_count: "Karşılaştırma Toplamı",
  current_entity_count: "Birinci Grup Randevu Sayısı",
  baseline_entity_count: "İkinci Grup Randevu Sayısı",
  group_count: "Grup Sayısı",
  total_appointments: "Toplam Randevu",
  average_appointments: "Ortalama Randevu",
  minimum_appointments: "En Düşük Randevu",
  maximum_appointments: "En Yüksek Randevu",
  max_to_average_ratio: "En Yüksek / Ortalama Oranı",
  top_10_percent_share: "İlk %10 Grubun Payı",
  current_rate: "Mevcut Dönem Oranı",
  baseline_rate: "Önceki Dönem Oranı",
  appointments_per_patient: "Hasta Başına Randevu",
  repeat_patient_count: "Tekrar Randevu Alan Hasta Sayısı",
  appointment_duration_average: "Ortalama Randevu Süresi",
  average_appointment_duration: "Ortalama Randevu Süresi",
  appointment_duration_minimum: "En Kısa Randevu Süresi",
  appointment_duration_maximum: "En Uzun Randevu Süresi",
  appointments_per_doctor: "Doktor Bazlı Randevu Sayısı",
  appointments_per_department: "Bölüm Bazlı Randevu Sayısı",
  appointments_per_branch: "Şube Bazlı Randevu Sayısı",
  appointments_per_source: "Kaynak Bazlı Randevu Sayısı",
  appointments_per_type: "Tip Bazlı Randevu Sayısı",
  daily_appointment_count: "Günlük Randevu Sayısı",
  weekly_appointment_count: "Haftalık Randevu Sayısı",
  monthly_appointment_count: "Aylık Randevu Sayısı",
  daily_average_appointment_count: "Günlük Ortalama Randevu Sayısı",
  appointment_lead_time_average: "Ortalama Randevu Alma Süresi",
  same_day_booking_count: "Aynı Gün Alınan Randevu Sayısı",
  same_day_booking_rate: "Aynı Gün Randevu Oranı",
  protocol_opening_delay_average: "Ortalama Protokol Açılış Gecikmesi",
  actual_duration_from_dates: "Fiili Randevu Süresi",
  duration_difference: "Planlanan-Fiili Süre Farkı",
  completed_appointment_count: "Gerçekleşen Randevu Sayısı",
  completed_appointment_rate: "Gerçekleşme Oranı",
  protocol_created_count: "Protokol Açılan Randevu Sayısı",
  protocol_conversion_rate: "Protokole Dönüşüm Oranı",
};

/**
 * Ham SQL/şema sütun adı (view column) veya jenerik context/planning id'si
 * -> Türkçe etiket (AI-INTELLIGENCE-013). Backend'deki
 * DIMENSION_LABELS_TR ile eş tutulmalıdır. Metrik alias'larının aksine bu
 * anahtarlar büyük/küçük harfe duyarlıdır (PascalCase SQL sütun adları).
 */
export const DIMENSION_LABELS_TR: Record<string, string> = {
  SubeAdi: "Şube",
  GenelRandevuBolumAdi: "Bölüm",
  BolumId: "Bölüm",
  RandevuTipiAdi: "Randevu Tipi",
  RandevuDurumu: "Randevu Durumu",
  GenelRandevuKaynakAdi: "Randevu Kaynağı",
  DoktorId: "Doktor",
  Uyruk: "Uyruk",
  CinsiyetId: "Cinsiyet",
  KategoriAdi: "Kategori",
  HizmetAdi: "Hizmet",
  RandevuyuVeren: "Randevuyu Veren",
  BaslangicTarihi: "Başlangıç Tarihi",
  BitisTarihi: "Bitiş Tarihi",
  RandevuSuresi: "Randevu Süresi",
  HastaAdi: "Hasta Adı",
  HastaSoyadi: "Hasta Soyadı",
  DogumTarihi: "Doğum Tarihi",
  CreatedDate: "Oluşturulma Tarihi",
  age_group: "Yaş Grubu",
  // Jenerik canonical dimension id'leri (context/analytical_signals, API).
  branch: "Şube",
  doctor: "Doktor",
  department: "Bölüm",
  status: "Randevu Durumu",
  service: "Hizmet",
  category: "Kategori",
  source: "Randevu Kaynağı",
  type: "Randevu Tipi",
  date: "Tarih",
};

const METRIC_UNITS_TR: Record<string, string> = {
  appointment_count: "randevu",
  cohort_total_count: "randevu",
  total_appointments: "randevu",
  current_period_count: "randevu",
  baseline_period_count: "randevu",
  daily_appointment_count: "randevu",
  weekly_appointment_count: "randevu",
  monthly_appointment_count: "randevu",
  daily_average_appointment_count: "randevu",
  completed_appointment_count: "randevu",
  appointment_duration_average: "dk",
  average_appointment_duration: "dk",
  appointment_duration_minimum: "dk",
  appointment_duration_maximum: "dk",
  actual_duration_from_dates: "dk",
  duration_difference: "dk",
};

/** Alias için Türkçe etiket; bilinmeyenler okunur hâle getirilir. */
export function labelFor(alias: string): string {
  const normalized = alias.trim().toLowerCase();
  if (METRIC_LABELS_TR[normalized]) return METRIC_LABELS_TR[normalized];
  return alias
    .replace(/_/g, " ")
    .trim()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Oran mı sayı mı: alias adından biçim seçimi (backend ile aynı kural). */
export function isRateAlias(alias: string): boolean {
  const lowered = alias.toLowerCase();
  if (
    lowered.includes("count") ||
    lowered.includes("total") ||
    lowered.includes("sayi") ||
    lowered.includes("adet")
  ) {
    return false;
  }
  return (
    lowered.endsWith("_rate") ||
    lowered.endsWith("_percentage") ||
    lowered.endsWith("_share") ||
    lowered.endsWith("_ratio") ||
    lowered === "percentage_change" ||
    lowered === "rate_point_change" ||
    lowered.includes("oran") ||
    lowered.includes("yuzde")
  );
}

/** 678866 -> "678.866" (Türkçe binlik ayraç). */
export function formatNumberTr(value: number): string {
  if (Number.isInteger(value)) {
    return value.toLocaleString("tr-TR");
  }
  return value.toLocaleString("tr-TR", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
}

/** 73.409332 -> "%73,4" (ondalık ayırıcı virgül, en fazla 1 ondalık). */
export function formatPercentTr(value: number): string {
  return `%${value.toLocaleString("tr-TR", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 1,
  })}`;
}

/** Alias'a göre doğru Türkçe biçim. */
export function formatValueTr(alias: string, value: number): string {
  if (isRateAlias(alias)) return formatPercentTr(value);
  const formatted = formatNumberTr(value);
  const unit = METRIC_UNITS_TR[alias.trim().toLowerCase()];
  return unit ? `${formatted} ${unit}` : formatted;
}

// ── SQL result table column presentation (AI-INTELLIGENCE-013) ─────────────
//
// The backend attaches `column_metadata` (key/label/format/unit) to
// query_result whenever it can. This resolver is the frontend fallback for
// when that metadata is missing (older API responses, degraded mapping) —
// it reuses this SAME centralized catalog, never a second independent
// mapping, per the resolution priority: planned metric/dimension metadata
// (resolvedMetrics/resolvedDimensions) -> centralized label catalog ->
// known view-column mapping -> readable fallback.
export function getColumnLabel(
  column: string,
  resolvedMetrics?: string[] | null,
  resolvedDimensions?: string[] | null,
): string {
  if (!column) return "";
  if (resolvedMetrics?.includes(column)) return labelFor(column);
  if (resolvedDimensions?.includes(column)) {
    return DIMENSION_LABELS_TR[column] ?? labelFor(column);
  }
  const normalized = column.trim().toLowerCase();
  if (METRIC_LABELS_TR[normalized]) return METRIC_LABELS_TR[normalized];
  if (DIMENSION_LABELS_TR[column]) return DIMENSION_LABELS_TR[column];
  return labelFor(column);
}

export type ColumnFormat =
  "text" | "integer" | "decimal" | "percentage" | "duration" | "date" | "datetime";

export interface ColumnMetadata {
  key: string;
  label: string;
  format: ColumnFormat;
  unit: string | null;
  /** Retained in the result for internal/diagnostic use (e.g. DoktorId once
   * DoktorAdi has resolved) — the normal table hides it by default; the user
   * may still reveal it via column visibility controls. */
  hidden?: boolean;
}

const DURATION_COLUMNS = new Set(["RandevuSuresi"]);
const DATE_COLUMNS = new Set(["BaslangicTarihi", "BitisTarihi", "DogumTarihi", "CreatedDate"]);

function inferColumnFormat(column: string): { format: ColumnFormat; unit: string | null } {
  if (DURATION_COLUMNS.has(column)) return { format: "duration", unit: "dakika" };
  if (DATE_COLUMNS.has(column)) {
    return { format: column === "CreatedDate" ? "datetime" : "date", unit: null };
  }
  const normalized = column.trim().toLowerCase();
  if (isRateAlias(column)) return { format: "percentage", unit: "%" };
  const unit = METRIC_UNITS_TR[normalized];
  if (unit === "dk") return { format: "decimal", unit: "dakika" };
  if (unit) return { format: "integer", unit: null };
  if (normalized.endsWith("_count") || normalized === "count" || normalized === "row_count") {
    return { format: "integer", unit: null };
  }
  return { format: "text", unit: null };
}

/** Deterministic suffixing so two columns never export under the same header. */
function dedupeLabels(labels: string[]): string[] {
  const seen = new Map<string, number>();
  return labels.map((label) => {
    const count = seen.get(label) ?? 0;
    seen.set(label, count + 1);
    return count === 0 ? label : `${label} (${count + 1})`;
  });
}

/**
 * Resolves display column metadata for the SQL result table, preferring
 * backend-supplied `column_metadata` and safely deriving it otherwise.
 * Never crashes, never returns an empty label, and never renames `key`
 * (raw keys stay the source of truth for row access/sort/filter/export).
 */
export function resolveColumnMetadata(
  columns: string[],
  backendMetadata?: ColumnMetadata[] | null,
  resolvedMetrics?: string[] | null,
  resolvedDimensions?: string[] | null,
): ColumnMetadata[] {
  const byKey = new Map((backendMetadata ?? []).map((m) => [m.key, m]));
  const resolved = columns.map((column) => {
    const fromBackend = byKey.get(column);
    if (fromBackend && fromBackend.label) return fromBackend;
    const label = getColumnLabel(column, resolvedMetrics, resolvedDimensions) || column;
    const { format, unit } = inferColumnFormat(column);
    return { key: column, label, format, unit };
  });
  const dedupedLabels = dedupeLabels(resolved.map((m) => m.label));
  return resolved.map((m, i) => ({ ...m, label: dedupedLabels[i] }));
}

// ── Analytics/KPI card presentation ("Temel Göstergeler", AI-INTELLIGENCE-014) ─
//
// `AnalyticsResult.metrics` (backend app/analytics/analytics_engine.py) is a
// flat dict of internal, stable analytics keys (total/average/median/...).
// Those keys are NEVER renamed server-side — this section is the ONLY place
// that translates them for display, exactly like METRIC_LABELS_TR does for
// metric aliases and DIMENSION_LABELS_TR for view columns.

export const ANALYTICS_LABELS_TR: Record<string, string> = {
  count: "Kayıt Sayısı",
  total: "Toplam",
  average: "Ortalama",
  median: "Medyan",
  minimum: "En Düşük Değer",
  maximum: "En Yüksek Değer",
  highest_value: "En Yüksek Değer",
  lowest_value: "En Düşük Değer",
  difference: "Değişim",
  percentage_change: "Yüzdesel Değişim",
  growth_rate: "Büyüme Oranı",
  trend_direction: "Eğilim Yönü",
  endpoint_change: "İlk ve Son Dönem Değişimi",
  endpoint_percentage_change: "İlk ve Son Dönem Değişim Oranı",
  endpoint_direction: "Uç Dönem Eğilimi",
  slope: "Genel Eğilim Katsayısı",
  slope_direction: "Genel Eğilim Yönü",
  trend_consistency: "Eğilim Tutarlılığı",
  volatility: "Değişkenlik",
  top_category: "En Yüksek Kategori",
  bottom_category: "En Düşük Kategori",
  highest_period: "En Yüksek Dönem",
  lowest_period: "En Düşük Dönem",
  largest_change: "En Büyük Değişimin Görüldüğü Dönem",
  comparable_period_count: "Karşılaştırılabilir Dönem Sayısı",
  comparison_category_count: "Karşılaştırılan Kategori Sayısı",
  comparison_sufficient: "Karşılaştırma Yeterliliği",
  row_count: "Satır Sayısı",
  unique_count: "Tekil Değer Sayısı",
  missing_count: "Eksik Veri Sayısı",
  missing_rate: "Eksik Veri Oranı",
};

const TREND_DIRECTION_LABELS_TR: Record<string, string> = {
  upward: "Yükseliş",
  downward: "Düşüş",
  flat: "Yatay",
  mixed: "Karma",
  insufficient_data: "Yetersiz Veri",
};

const TREND_CONSISTENCY_LABELS_TR: Record<string, string> = {
  consistent_upward: "Tutarlı Yükseliş",
  consistent_downward: "Tutarlı Düşüş",
  mixed: "Karma Eğilim",
  flat: "Yatay Eğilim",
  insufficient_data: "Yetersiz Veri",
};

const BOOLEAN_LABELS_TR: Record<"true" | "false", string> = { true: "Evet", false: "Hayır" };
const SUFFICIENCY_LABELS_TR: Record<"true" | "false", string> = {
  true: "Yeterli",
  false: "Yetersiz",
};
export const CONFIDENCE_LABELS_TR: Record<string, string> = {
  HIGH: "Yüksek",
  MEDIUM: "Orta",
  LOW: "Düşük",
};

/** analytics.metrics anahtarları için Türkçe etiket; bilinmeyenler için okunur
 * bir geri dönüş üretir ve geliştirme modunda eksik eşlemeyi loglar. */
export function getAnalyticsLabel(key: string): string {
  if (!key) return "";
  if (ANALYTICS_LABELS_TR[key]) return ANALYTICS_LABELS_TR[key];
  if (import.meta.env?.DEV) {
    console.warn(`[presentation] unmapped analytics key "${key}" — using fallback label.`);
  }
  return key
    .replace(/_/g, " ")
    .trim()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

// KPI anahtarları yalnız oran/yüzde olarak sunulur.
const ANALYTICS_PERCENTAGE_KEYS = new Set([
  "percentage_change",
  "growth_rate",
  "endpoint_percentage_change",
  "volatility",
  "missing_rate",
]);
// Dönem etiketi taşıyan KPI'lar: tarih/ay biçiminde gösterilir.
const ANALYTICS_PERIOD_KEYS = new Set([
  "highest_period",
  "lowest_period",
  "largest_change",
  "first_comparable_period",
  "last_comparable_period",
]);
// Yön/eğilim enum'u taşıyan KPI'lar.
const ANALYTICS_DIRECTION_KEYS = new Set([
  "trend_direction",
  "endpoint_direction",
  "slope_direction",
]);
const ANALYTICS_CONSISTENCY_KEYS = new Set(["trend_consistency"]);
// Evet/Hayır olarak gösterilecek boolean KPI'lar.
const ANALYTICS_SUFFICIENCY_KEYS = new Set(["comparison_sufficient"]);
const ANALYTICS_BOOLEAN_KEYS = new Set(["comparison_excluded_partial_period"]);

/**
 * Bir analytics.metrics değerini Türkçe biçimde sunar. Ham API değeri asla
 * değiştirilmez — yalnızca görünüm string'i üretilir.
 */
export function formatAnalyticsValue(key: string, value: unknown): string {
  if (value == null) return tr.common.noData;
  if (ANALYTICS_DIRECTION_KEYS.has(key) && typeof value === "string") {
    return TREND_DIRECTION_LABELS_TR[value] ?? value;
  }
  if (ANALYTICS_CONSISTENCY_KEYS.has(key) && typeof value === "string") {
    return TREND_CONSISTENCY_LABELS_TR[value] ?? value;
  }
  if (ANALYTICS_SUFFICIENCY_KEYS.has(key) && typeof value === "boolean") {
    return SUFFICIENCY_LABELS_TR[value ? "true" : "false"];
  }
  if (ANALYTICS_BOOLEAN_KEYS.has(key) && typeof value === "boolean") {
    return BOOLEAN_LABELS_TR[value ? "true" : "false"];
  }
  if (typeof value === "boolean") return BOOLEAN_LABELS_TR[value ? "true" : "false"];
  if (ANALYTICS_PERIOD_KEYS.has(key) && typeof value === "string") {
    return formatPeriodTr(value);
  }
  if (typeof value === "number") {
    if (ANALYTICS_PERCENTAGE_KEYS.has(key)) return formatPercentTr(value);
    if (key.endsWith("_count")) return formatNumberTr(value);
    return formatNumberTr(value);
  }
  return String(value);
}

const MONTHS_TR = [
  "Ocak",
  "Şubat",
  "Mart",
  "Nisan",
  "Mayıs",
  "Haziran",
  "Temmuz",
  "Ağustos",
  "Eylül",
  "Ekim",
  "Kasım",
  "Aralık",
];

/** "2026-06" -> "Haziran 2026"; "2026-06-01" -> "1 Haziran 2026"; datetime -> + saat. */
function formatPeriodTr(value: string): string {
  const monthOnly = /^(\d{4})-(\d{2})$/.exec(value.trim());
  if (monthOnly) {
    const month = MONTHS_TR[Number(monthOnly[2]) - 1];
    return month ? `${month} ${monthOnly[1]}` : value;
  }
  const dateMatch = /^(\d{4})-(\d{2})-(\d{2})(?:[T\s](\d{2}):(\d{2}))?/.exec(value.trim());
  if (dateMatch) {
    const [, year, month, day, hour, minute] = dateMatch;
    const monthName = MONTHS_TR[Number(month) - 1];
    if (!monthName) return value;
    const base = `${Number(day)} ${monthName} ${year}`;
    return hour != null ? `${base} ${hour}:${minute}` : base;
  }
  return value;
}

// KPI anahtarları arasında aynı sayıyı iki kez gösteren takma adlar — sadece
// kanonik anahtar kart olarak gösterilir (AI-INTELLIGENCE-014 #9).
const ANALYTICS_ALIAS_OF: Record<string, string> = {
  highest_value: "maximum",
  lowest_value: "minimum",
  growth_rate: "percentage_change",
  endpoint_change: "difference",
  endpoint_direction: "trend_direction",
};

// Kullanıcı dostu, sabit KPI sırası (obje anahtar sırasına güvenilmez).
const ANALYTICS_KPI_ORDER = [
  "count",
  "row_count",
  "total",
  "average",
  "median",
  "maximum",
  "minimum",
  "difference",
  "percentage_change",
  "trend_direction",
  "slope_direction",
  "trend_consistency",
  "slope",
  "volatility",
  "top_category",
  "bottom_category",
  "highest_period",
  "lowest_period",
  "largest_change",
  "comparable_period_count",
  "comparison_category_count",
  "comparison_sufficient",
  "unique_count",
  "missing_count",
  "missing_rate",
];

// Geliştirici/iç kullanım alanları — "Temel Göstergeler" kartlarında hiç
// gösterilmez (liste/nesne değerler zaten otomatik elenir).
const ANALYTICS_HIDDEN_KEYS = new Set([
  "count",
  "row_count",
  "slope_direction_tr",
  "endpoint_direction_tr",
  "first_comparable_period",
  "last_comparable_period",
  "comparison_excluded_partial_period",
]);

export interface AnalyticsKpiCardOptions {
  /** This turn's resolved metric ids. A single unambiguous metric is exposed
   * as shared card context instead of being repeated in every KPI label. */
  resolvedMetrics?: string[] | null;
  /** Hard cap on rendered cards (compact card grids). */
  limit?: number;
}

/**
 * Builds ordered, deduped, Türkçe-labeled KPI cards from
 * `AnalyticsResult.metrics` (+ optional comparison fields). Internal keys
 * are read-only inputs here — never mutated, never renamed upstream.
 */
export function buildAnalyticsCards(
  metrics: Record<string, unknown> | null | undefined,
  options: AnalyticsKpiCardOptions = {},
): MetricCard[] {
  if (!metrics) return [];
  const metricPrefix =
    options.resolvedMetrics?.length === 1 ? labelFor(options.resolvedMetrics[0]) : null;

  const scalarKeys = Object.keys(metrics).filter((key) => {
    const value = metrics[key];
    if (ANALYTICS_HIDDEN_KEYS.has(key)) return false;
    if (value == null) return false;
    if (typeof value === "object") return false; // lists/dicts (top_n, distribution, ...)
    // An alias is only dropped when its canonical counterpart is ALSO present;
    // otherwise the alias is the only signal available and must still render.
    const canonical = ANALYTICS_ALIAS_OF[key];
    if (canonical && metrics[canonical] != null) return false;
    return true;
  });

  scalarKeys.sort((a, b) => {
    const ai = ANALYTICS_KPI_ORDER.indexOf(a);
    const bi = ANALYTICS_KPI_ORDER.indexOf(b);
    if (ai === -1 && bi === -1) return 0;
    if (ai === -1) return 1;
    if (bi === -1) return -1;
    return ai - bi;
  });

  const cards = scalarKeys.map((key) => {
    const kpiLabel = getAnalyticsLabel(key);
    return {
      label: kpiLabel,
      value: formatAnalyticsValue(key, metrics[key]),
      context: metricPrefix ?? undefined,
    };
  });

  return options.limit ? cards.slice(0, options.limit) : cards;
}

export interface MetricCard {
  label: string;
  value: string;
  isEmpty?: boolean;
  context?: string;
}

/**
 * Tek satırlık sayısal özet sonuçları metrik kartlarına çevirir.
 * En değerli 5 alanla sınırlanır; teknik label alanları atlanır.
 */
export function buildMetricCards(
  columns: string[],
  rows: Array<Record<string, string | number | null>>,
): MetricCard[] {
  if (rows.length !== 1) return [];
  const row = rows[0];
  const cards: MetricCard[] = [];
  for (const column of columns) {
    const value = row[column];
    const normalized = column.trim().toLowerCase();
    if (value == null || (typeof value === "number" && Number.isNaN(value))) {
      if (METRIC_LABELS_TR[normalized]) {
        cards.push({ label: labelFor(column), value: tr.common.noData, isEmpty: true });
        if (cards.length >= 5) break;
      }
      continue;
    }
    if (typeof value !== "number") continue;
    cards.push({ label: labelFor(column), value: formatValueTr(column, value) });
    if (cards.length >= 5) break;
  }
  return cards;
}
