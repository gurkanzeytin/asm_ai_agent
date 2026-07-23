import {
  useCallback,
  useId,
  useMemo,
  useRef,
  useState,
  useEffect,
  lazy,
  Suspense,
  type KeyboardEvent,
  type MouseEvent as ReactMouseEvent,
} from "react";
import {
  Search,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  Download,
  Copy,
  Check,
  Database,
  ChevronLeft,
  ChevronRight,
  BarChart3,
  Sigma,
  Filter,
  Settings2,
  GripVertical,
  X,
  FileJson,
  FileCode,
  Trash2,
  ListChecks,
  Rows3,
  Maximize2,
  AlertTriangle,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Checkbox } from "@/components/ui/checkbox";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SqlRowDrawer } from "./SqlRowDrawer";
import { SqlSummaryStats } from "./SqlSummaryStats";
import { tr } from "@/locales/tr";
import { chartTypeFromRecommendation } from "./sql-chart-data";
import { formatSqlCell } from "@/lib/sql-cell-format";
import { buildMetricCards, resolveColumnMetadata, type ColumnMetadata } from "@/lib/presentation";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { uiTransition } from "@/lib/ui-motion";
import { DEFAULT_TABLE_PAGE_SIZE, MAX_UI_ROWS_PER_PAGE } from "@/lib/result-limits";

const LazySqlChartPanel = lazy(() =>
  import("./SqlChartPanel").then((module) => ({ default: module.SqlChartPanel })),
);

export interface SqlResult {
  columns: string[];
  rows: Array<Record<string, string | number | null>>;
  /** Backend-supplied presentation metadata (label/format/unit) per raw column key. */
  columnMetadata?: ColumnMetadata[];
  /** This turn's resolved metric/dimension ids, used for label resolution priority. */
  resolvedMetrics?: string[];
  resolvedDimensions?: string[];
  query?: string;
  durationMs?: number;
  visualization?: string | null;
  /** Technical execution metadata; never interpreted as business KPIs. */
  technicalRowCount?: number;
  resultShape?: string;
  sourceRecordCount?: number | null;
  resultGroupCount?: number | null;
  returnedRowCount?: number;
  displayedRowCount?: number;
  resultTruncated?: boolean;
  hasMore?: boolean;
  totalCount?: number | null;
  appliedLimit?: number;
}

interface Props {
  data: SqlResult;
  pageSize?: number;
  displayMode?: "table" | "chart" | "both";
  /** Switch to virtualized scrolling above this row count. Default 100. */
  virtualizeThreshold?: number;
  /** Approx row height in px for the virtualizer. */
  rowHeight?: number;
  /** Max viewport height for virtualized scroll area. */
  virtualHeight?: number;
  allowFullscreen?: boolean;
}

type SortDir = "asc" | "desc" | null;
type FilterOperator = "eq" | "contains" | "gt" | "lt" | "gte" | "lte" | "empty" | "notEmpty";
type ExportFormat = "csv" | "json" | "sql";
type TableDensity = "compact" | "normal" | "comfortable";

interface FilterRule {
  id: string;
  column: string;
  operator: FilterOperator;
  value: string;
}

interface RowMeta {
  row: Record<string, string | number | null>;
  idx: number;
}

export function SqlResultsTable({
  data,
  pageSize = DEFAULT_TABLE_PAGE_SIZE,
  displayMode = "table",
  virtualizeThreshold = 100,
  rowHeight = 32,
  virtualHeight = 420,
  allowFullscreen = true,
}: Props) {
  const recommendedChartType = chartTypeFromRecommendation(data.visualization);
  const chartOnly = displayMode === "chart";
  const tableVisible = displayMode !== "chart";
  const chartAllowed = displayMode !== "table";
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>(null);
  const [page, setPage] = useState(1);
  const [copied, setCopied] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [focusedRow, setFocusedRow] = useState<number | null>(null);
  const [showStats, setShowStats] = useState(false);
  const [showChart, setShowChart] = useState(
    chartOnly || (chartAllowed && Boolean(recommendedChartType)),
  );
  const [density, setDensity] = useState<TableDensity>("normal");
  const [fullscreenOpen, setFullscreenOpen] = useState(false);

  // Filters & column management
  const [filters, setFilters] = useState<FilterRule[]>([]);
  const [columnOrder, setColumnOrder] = useState<string[]>(data.columns);
  const isHiddenByDefault = useCallback(
    (column: string) => data.columnMetadata?.find((m) => m.key === column)?.hidden === true,
    [data.columnMetadata],
  );
  const [columnVisibility, setColumnVisibility] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(data.columns.map((c) => [c, !isHiddenByDefault(c)])),
  );
  const [columnWidths, setColumnWidths] = useState<Record<string, number>>(() =>
    Object.fromEntries(data.columns.map((c) => [c, 140])),
  );
  const [selectedRows, setSelectedRows] = useState<Set<number>>(new Set());
  const [sqlTableName, setSqlTableName] = useState("results");
  const safePageSize = Math.min(Math.max(1, pageSize), MAX_UI_ROWS_PER_PAGE);
  const safeRows = useMemo(() => data.rows.slice(0, MAX_UI_ROWS_PER_PAGE), [data.rows]);
  const clientTrimmed = data.rows.length > safeRows.length;
  const isTruncated = Boolean(data.resultTruncated || data.hasMore || clientTrimmed);

  const tableId = useId();
  const searchId = useId();
  const rowRefs = useRef<Array<HTMLTableRowElement | null>>([]);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const resizeState = useRef<{ col: string; startX: number; startW: number } | null>(null);

  // Keep column management in sync if data changes
  useEffect(() => {
    setColumnOrder((prev) => {
      const existing = new Set(prev);
      const added = data.columns.filter((c) => !existing.has(c));
      return [...prev.filter((c) => data.columns.includes(c)), ...added];
    });
    setColumnVisibility((prev) => {
      const next: Record<string, boolean> = {};
      for (const c of data.columns) next[c] = prev[c] ?? !isHiddenByDefault(c);
      return next;
    });
    setColumnWidths((prev) => {
      const next: Record<string, number> = {};
      for (const c of data.columns) next[c] = prev[c] ?? 140;
      return next;
    });
    setSelectedRows(new Set());
  }, [data.columns, safeRows.length, isHiddenByDefault]);

  const visibleColumns = useMemo(
    () => columnOrder.filter((c) => columnVisibility[c] && data.columns.includes(c)),
    [columnOrder, columnVisibility, data.columns],
  );

  // Presentation metadata (Türkçe label/format/unit) per raw column key.
  // Raw keys (`data.columns`) remain the source of truth for row access,
  // sorting, filtering, and exports — only header text and cell formatting
  // read from this map (AI-INTELLIGENCE-013).
  const columnMeta = useMemo<Record<string, ColumnMetadata>>(() => {
    const resolved = resolveColumnMetadata(
      data.columns,
      data.columnMetadata,
      data.resolvedMetrics,
      data.resolvedDimensions,
    );
    return Object.fromEntries(resolved.map((m) => [m.key, m]));
  }, [data.columns, data.columnMetadata, data.resolvedMetrics, data.resolvedDimensions]);
  const columnLabel = (col: string) => columnMeta[col]?.label || col;

  const matchFilter = (
    value: string | number | null,
    operator: FilterOperator,
    filterValue: string,
  ) => {
    if (operator === "empty") return value == null || String(value).trim() === "";
    if (operator === "notEmpty") return value != null && String(value).trim() !== "";
    const str = String(value ?? "").toLowerCase();
    const fv = filterValue.toLowerCase();
    const num = Number(value);
    const fnum = Number(filterValue);
    switch (operator) {
      case "eq":
        return str === fv;
      case "contains":
        return str.includes(fv);
      case "gt":
        return !isNaN(num) && !isNaN(fnum) && num > fnum;
      case "lt":
        return !isNaN(num) && !isNaN(fnum) && num < fnum;
      case "gte":
        return !isNaN(num) && !isNaN(fnum) && num >= fnum;
      case "lte":
        return !isNaN(num) && !isNaN(fnum) && num <= fnum;
      default:
        return true;
    }
  };

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const rowsWithIdx: RowMeta[] = safeRows.map((row, idx) => ({ row, idx }));
    return rowsWithIdx.filter(({ row }) => {
      const globalMatch =
        !q ||
        data.columns.some((c) =>
          String(row[c] ?? "")
            .toLowerCase()
            .includes(q),
        );
      const filterMatch = filters.every((f) => matchFilter(row[f.column], f.operator, f.value));
      return globalMatch && filterMatch;
    });
  }, [data.columns, safeRows, query, filters]);

  const sorted = useMemo(() => {
    if (!sortKey || !sortDir || !visibleColumns.includes(sortKey)) return filtered;
    const dir = sortDir === "asc" ? 1 : -1;
    return [...filtered].sort((a, b) => {
      const av = a.row[sortKey];
      const bv = b.row[sortKey];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
      return String(av).localeCompare(String(bv), undefined, { numeric: true }) * dir;
    });
  }, [filtered, sortKey, sortDir, visibleColumns]);
  const scalarMetricCards = useMemo(
    () =>
      buildMetricCards(
        visibleColumns,
        sorted.map((item) => item.row),
      ),
    [visibleColumns, sorted],
  );
  const showScalarMetricPanel = chartOnly && scalarMetricCards.length > 0;

  const isVirtualized = sorted.length > virtualizeThreshold;
  const totalPages = Math.max(1, Math.ceil(sorted.length / safePageSize));
  const safePage = Math.min(page, totalPages);
  const pageRows = isVirtualized
    ? sorted
    : sorted.slice((safePage - 1) * safePageSize, safePage * safePageSize);

  const virtualizer = useVirtualizer({
    count: isVirtualized ? sorted.length : 0,
    getScrollElement: () => scrollRef.current,
    estimateSize: () =>
      density === "compact"
        ? Math.max(26, rowHeight - 4)
        : density === "comfortable"
          ? 40
          : rowHeight,
    overscan: 10,
  });

  const cellPadding =
    density === "compact" ? "py-1.5" : density === "comfortable" ? "py-3" : "py-2";
  const cycleDensity = () =>
    setDensity((current) =>
      current === "compact" ? "normal" : current === "normal" ? "comfortable" : "compact",
    );

  // Selection helpers
  const allVisibleSelected =
    pageRows.length > 0 && pageRows.every(({ idx }) => selectedRows.has(idx));
  const someVisibleSelected =
    pageRows.some(({ idx }) => selectedRows.has(idx)) && !allVisibleSelected;

  const toggleSelectRow = (idx: number) => {
    setSelectedRows((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const toggleSelectAllVisible = () => {
    setSelectedRows((prev) => {
      const next = new Set(prev);
      if (allVisibleSelected) {
        pageRows.forEach(({ idx }) => next.delete(idx));
      } else {
        pageRows.forEach(({ idx }) => next.add(idx));
      }
      return next;
    });
  };

  const clearSelection = () => setSelectedRows(new Set());

  const toggleSort = (col: string) => {
    let nextKey: string | null = col;
    let nextDir: SortDir = "asc";
    if (sortKey !== col) {
      nextKey = col;
      nextDir = "asc";
    } else if (sortDir === "asc") {
      nextDir = "desc";
    } else if (sortDir === "desc") {
      nextKey = null;
      nextDir = null;
    }
    setSortKey(nextKey);
    setSortDir(nextDir);
    setAnnouncement(
      nextKey && nextDir ? tr.sqlTable.sortedBy(col, nextDir) : tr.sqlTable.sortCleared,
    );
  };

  const ariaSortFor = (col: string): "ascending" | "descending" | "none" => {
    if (sortKey !== col || !sortDir) return "none";
    return sortDir === "asc" ? "ascending" : "descending";
  };

  const escapeCsv = (v: unknown) => {
    const s = v == null ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };

  // Export/copy headers use Türkçe display labels; row data always reads
  // raw values via visibleColumns (row[c]) — labels never touch data access.
  const visibleColumnLabels = visibleColumns.map(columnLabel);

  const toCsv = (rows: RowMeta[]) => {
    const header = ["#", ...visibleColumnLabels].map(escapeCsv).join(",");
    const body = rows
      .map(({ row }, i) => [i + 1, ...visibleColumns.map((c) => escapeCsv(row[c]))].join(","))
      .join("\n");
    return `${header}\n${body}`;
  };

  const toTsv = (rows: RowMeta[]) => {
    const header = ["#", ...visibleColumnLabels].join("\t");
    const body = rows
      .map(({ row }, i) => [i + 1, ...visibleColumns.map((c) => row[c] ?? "")].join("\t"))
      .join("\n");
    return `${header}\n${body}`;
  };

  const toJson = (rows: RowMeta[]) => {
    const payload = rows.map(({ row }) =>
      Object.fromEntries(visibleColumns.map((c) => [c, row[c]])),
    );
    return JSON.stringify(payload, null, 2);
  };

  const toSqlInsert = (rows: RowMeta[], table: string) => {
    const cols = visibleColumns.map((c) => `"${c}"`).join(", ");
    const values = rows
      .map(({ row }) => {
        const vals = visibleColumns
          .map((c) => {
            const v = row[c];
            if (v == null) return "NULL";
            if (typeof v === "number") return String(v);
            return `'${String(v).replace(/'/g, "''")}'`;
          })
          .join(", ");
        return `INSERT INTO "${table}" (${cols}) VALUES (${vals});`;
      })
      .join("\n");
    return values;
  };

  const triggerDownload = (content: string, filename: string, type: string) => {
    const blob = new Blob([content], { type });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  const exportRows = (rows: RowMeta[], format: ExportFormat) => {
    const timestamp = Date.now();
    if (format === "csv") {
      const csv = toCsv(rows);
      triggerDownload(csv, `sql-results-${timestamp}.csv`, "text/csv;charset=utf-8");
      toast.success(tr.sqlTable.csvExported, {
        description: tr.sqlTable.exported("CSV", rows.length),
      });
      setAnnouncement(tr.sqlTable.exported("CSV", rows.length));
    } else if (format === "json") {
      const json = toJson(rows);
      triggerDownload(json, `sql-results-${timestamp}.json`, "application/json");
      toast.success(tr.sqlTable.exported("JSON", rows.length));
      setAnnouncement(tr.sqlTable.exported("JSON", rows.length));
    } else if (format === "sql") {
      const sql = toSqlInsert(rows, sqlTableName || "results");
      triggerDownload(sql, `sql-results-${timestamp}.sql`, "text/plain;charset=utf-8");
      toast.success(tr.sqlTable.sqlExported(rows.length));
      setAnnouncement(tr.sqlTable.sqlExported(rows.length));
    }
  };

  const exportAll = (format: ExportFormat) => exportRows(sorted, format);
  const exportSelected = (format: ExportFormat) => {
    const selected = sorted.filter(({ idx }) => selectedRows.has(idx));
    if (selected.length === 0) {
      toast.warning(tr.sqlTable.noRowsSelected);
      return;
    }
    exportRows(selected, format);
  };

  const copyTable = async () => {
    const tsv = toTsv(sorted);
    try {
      await navigator.clipboard.writeText(tsv);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
      toast.success(tr.sqlTable.tableCopied, { description: tr.sqlTable.tableCopiedDescription });
      setAnnouncement(tr.sqlTable.copiedToClipboard);
    } catch {
      toast.error(tr.sqlTable.copyFailed);
      setAnnouncement(tr.sqlTable.copyFailed);
    }
  };

  const copySelected = async () => {
    const selected = sorted.filter(({ idx }) => selectedRows.has(idx));
    if (selected.length === 0) {
      toast.warning(tr.sqlTable.noRowsSelected);
      return;
    }
    const tsv = toTsv(selected);
    try {
      await navigator.clipboard.writeText(tsv);
      toast.success(tr.sqlTable.selectedRowsCopied(selected.length));
      setAnnouncement(tr.sqlTable.selectedRowsCopied(selected.length));
    } catch {
      toast.error(tr.sqlTable.copyFailed);
      setAnnouncement(tr.sqlTable.copyFailed);
    }
  };

  const addFilter = (column: string, operator: FilterOperator, value: string) => {
    setFilters((prev) => [
      ...prev.filter((filter) => filter.column !== column),
      { id: makeId(), column, operator, value },
    ]);
    setPage(1);
    setAnnouncement(tr.sqlTable.filterAdded(column));
  };

  const removeFilter = (id: string) => {
    setFilters((prev) => prev.filter((f) => f.id !== id));
  };

  const clearFilters = () => {
    setFilters([]);
    setQuery("");
    setAnnouncement(tr.sqlTable.filtersCleared);
  };

  const toggleColumnVisibility = (col: string) => {
    if (columnVisibility[col] && visibleColumns.length === 1) {
      toast.info(tr.sqlTable.keepOneColumn);
      return;
    }
    setColumnVisibility((prev) => ({ ...prev, [col]: !prev[col] }));
  };

  const showAllColumns = () => {
    setColumnVisibility(Object.fromEntries(data.columns.map((c) => [c, true])));
  };

  // Resize handlers
  const startResize = (e: ReactMouseEvent, col: string) => {
    e.preventDefault();
    e.stopPropagation();
    resizeState.current = { col, startX: e.clientX, startW: columnWidths[col] ?? 140 };
    document.addEventListener("mousemove", onResizeMove);
    document.addEventListener("mouseup", onResizeUp);
  };

  const onResizeMove = (e: globalThis.MouseEvent) => {
    if (!resizeState.current) return;
    const { col, startX, startW } = resizeState.current;
    const nextW = Math.max(60, startW + (e.clientX - startX));
    setColumnWidths((prev) => ({ ...prev, [col]: nextW }));
  };

  const onResizeUp = () => {
    resizeState.current = null;
    document.removeEventListener("mousemove", onResizeMove);
    document.removeEventListener("mouseup", onResizeUp);
  };

  // Drag-and-drop reorder
  const [draggingCol, setDraggingCol] = useState<string | null>(null);

  const onDragStart = (e: React.DragEvent<HTMLTableHeaderCellElement>, col: string) => {
    setDraggingCol(col);
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", col);
  };

  const onDragOver = (e: React.DragEvent<HTMLTableHeaderCellElement>) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  };

  const onDrop = (e: React.DragEvent<HTMLTableHeaderCellElement>, targetCol: string) => {
    e.preventDefault();
    const sourceCol = e.dataTransfer.getData("text/plain") || draggingCol;
    setDraggingCol(null);
    if (!sourceCol || sourceCol === targetCol) return;
    setColumnOrder((prev) => {
      const next = [...prev];
      const from = next.indexOf(sourceCol);
      const to = next.indexOf(targetCol);
      if (from === -1 || to === -1) return prev;
      next.splice(from, 1);
      next.splice(to, 0, sourceCol);
      return next;
    });
    const targetIndex = columnOrder.indexOf(targetCol);
    setAnnouncement(tr.sqlTable.columnMoved(sourceCol, targetIndex + 1));
  };

  const openRow = (idx: number) => {
    setSelectedIndex(idx);
    setDrawerOpen(true);
  };

  const focusRowLocal = (localIdx: number) => {
    const el = rowRefs.current[localIdx];
    if (el) el.focus();
  };

  const focusRowVirtual = (absIdx: number) => {
    const clamped = Math.max(0, Math.min(sorted.length - 1, absIdx));
    virtualizer.scrollToIndex(clamped, { align: "auto" });
    setFocusedRow(clamped);
    requestAnimationFrame(() => {
      const el = document.getElementById(`${tableId}-row-${clamped}`);
      if (el) (el as HTMLElement).focus();
    });
  };

  const onRowKeyDown = (
    e: KeyboardEvent<HTMLTableRowElement>,
    localIdx: number,
    absIdx: number,
  ) => {
    switch (e.key) {
      case "Enter":
      case " ":
        e.preventDefault();
        openRow(absIdx);
        break;
      case "ArrowDown":
        e.preventDefault();
        if (isVirtualized) focusRowVirtual(absIdx + 1);
        else focusRowLocal(Math.min(pageRows.length - 1, localIdx + 1));
        break;
      case "ArrowUp":
        e.preventDefault();
        if (isVirtualized) focusRowVirtual(absIdx - 1);
        else focusRowLocal(Math.max(0, localIdx - 1));
        break;
      case "PageDown":
        e.preventDefault();
        if (isVirtualized) focusRowVirtual(absIdx + 10);
        break;
      case "PageUp":
        e.preventDefault();
        if (isVirtualized) focusRowVirtual(absIdx - 10);
        break;
      case "Home":
        e.preventDefault();
        if (isVirtualized) focusRowVirtual(0);
        else focusRowLocal(0);
        break;
      case "End":
        e.preventDefault();
        if (isVirtualized) focusRowVirtual(sorted.length - 1);
        else focusRowLocal(pageRows.length - 1);
        break;
    }
  };

  const goPrev = () => {
    if (safePage > 1) {
      setPage((p) => Math.max(1, p - 1));
      setAnnouncement(tr.sqlTable.pageAnnouncement(safePage - 1, totalPages));
    }
  };
  const goNext = () => {
    if (safePage < totalPages) {
      setPage((p) => Math.min(totalPages, p + 1));
      setAnnouncement(tr.sqlTable.pageAnnouncement(safePage + 1, totalPages));
    }
  };

  const selectedRow = selectedIndex != null ? (sorted[selectedIndex]?.row ?? null) : null;

  const renderCells = (meta: RowMeta) => (
    <>
      {visibleColumns.map((c, colIdx) => {
        const colMeta = columnMeta[c];
        const formatted = formatSqlCell(c, meta.row[c], colMeta?.format, colMeta?.unit);
        return (
          <td
            key={c}
            className={cn(
              "border-b border-border/40 px-3 font-mono text-[11.5px] text-foreground/90",
              cellPadding,
              colIdx === 0 && "sticky left-16 z-[1] bg-background/95 backdrop-blur",
            )}
            style={{ width: columnWidths[c], minWidth: columnWidths[c] }}
            title={formatted.raw !== formatted.display ? formatted.raw : undefined}
          >
            <span className={formatted.kind === "null" ? "text-muted-foreground/50" : undefined}>
              {formatted.display}
            </span>
          </td>
        );
      })}
    </>
  );

  const headerRow = (
    <tr className="bg-background/30">
      <th
        scope="col"
        aria-label={tr.sqlTable.rowNumber}
        className="sticky left-0 z-[2] w-16 min-w-16 border-b border-border/60 bg-background/95 px-2 py-2.5 text-right text-[10px] font-semibold uppercase tracking-wide text-muted-foreground/70 backdrop-blur"
      >
        <div className="flex items-center justify-start">
          <Checkbox
            checked={allVisibleSelected}
            aria-checked={allVisibleSelected ? true : someVisibleSelected ? "mixed" : false}
            aria-label={tr.sqlTable.selectAllVisible}
            onCheckedChange={toggleSelectAllVisible}
          />
        </div>
      </th>
      {visibleColumns.map((col, colIdx) => {
        const isActive = sortKey === col;
        const Icon = !isActive ? ArrowUpDown : sortDir === "asc" ? ArrowUp : ArrowDown;
        const label = columnLabel(col);
        const nextLabel = !isActive
          ? "artan sırala"
          : sortDir === "asc"
            ? "azalan sırala"
            : "sıralamayı kaldır";
        return (
          <th
            key={col}
            scope="col"
            aria-sort={ariaSortFor(col)}
            draggable
            onDragStart={(e) => onDragStart(e, col)}
            onDragOver={onDragOver}
            onDrop={(e) => onDrop(e, col)}
            className={cn(
              "group relative border-b border-border/60 p-0 text-left font-semibold text-muted-foreground",
              colIdx === 0 && "sticky left-16 z-[2] bg-background/95 backdrop-blur",
              draggingCol === col && "opacity-60",
            )}
            style={{
              width: columnWidths[col],
              minWidth: Math.max(90, columnWidths[col] ?? 90),
            }}
          >
            <div className="flex h-full w-full min-w-0 items-center pr-5">
              <button
                type="button"
                onClick={() => toggleSort(col)}
                aria-label={tr.sqlTable.sortAction(label, nextLabel)}
                title={label}
                className="inline-flex min-w-0 flex-1 items-center gap-1.5 px-3 py-2.5 text-left transition hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary/60"
              >
                <GripVertical
                  className="h-3 w-3 shrink-0 cursor-grab text-muted-foreground/30 active:cursor-grabbing"
                  aria-hidden="true"
                />
                <span className="min-w-0 flex-1 truncate">{label}</span>
                <Icon
                  aria-hidden="true"
                  className={cn(
                    "h-3 w-3 shrink-0 transition",
                    isActive ? "text-primary" : "text-muted-foreground/50",
                  )}
                />
              </button>
              <FilterPopover
                label={label}
                onApply={(op, val) => addFilter(col, op, val)}
                existing={filters.find((f) => f.column === col)}
                onClear={() => {
                  const f = filters.find((x) => x.column === col);
                  if (f) removeFilter(f.id);
                }}
              />
            </div>
            <div
              onMouseDown={(e) => startResize(e, col)}
              className="absolute right-0 top-0 h-full w-1 cursor-col-resize bg-transparent transition hover:bg-primary/30"
              aria-hidden="true"
            />
          </th>
        );
      })}
    </tr>
  );

  const hasActiveFilters = filters.length > 0 || query.trim() !== "";
  const truncationNotice = isTruncated
    ? data.totalCount != null
      ? tr.sqlTable.knownTotalTruncated(data.totalCount.toLocaleString("tr-TR"), safeRows.length)
      : tr.sqlTable.unknownTotalTruncated(safeRows.length)
    : null;

  return (
    <>
      <div className="glass mt-3 overflow-hidden rounded-lg">
        <span className="sr-only" aria-live="polite" aria-atomic="true">
          {announcement}
        </span>

        {/* Toolbar */}
        <div className="border-b border-border/60 px-3 py-2.5">
          <div className="flex items-center gap-3">
            <div className="flex min-w-0 items-center gap-2 pr-2 text-xs font-semibold text-muted-foreground">
              {chartOnly ? (
                <BarChart3 className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
              ) : (
                <Database className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
              )}
              <span>{chartOnly ? tr.sqlChart.title : tr.sqlTable.title}</span>
              <span className="rounded-full bg-primary/15 px-2 py-0.5 text-[10px] font-semibold text-primary">
                {sorted.length} {tr.sqlTable.rows}
              </span>
              {isVirtualized && (
                <span
                  className="rounded-full bg-accent/40 px-2 py-0.5 text-[10px] font-semibold text-muted-foreground"
                  title={tr.sqlTable.virtualizedTooltip}
                >
                  {tr.sqlTable.virtualized}
                </span>
              )}
              {data.durationMs != null && (
                <span className="text-[11px] font-normal text-muted-foreground/80">
                  / {data.durationMs} ms
                </span>
              )}
            </div>

            <div className="ml-auto flex shrink-0 items-center gap-2">
              {allowFullscreen && (
                <button
                  type="button"
                  onClick={() => setFullscreenOpen(true)}
                  aria-label={tr.sqlTable.openFullscreen}
                  title={tr.sqlTable.openFullscreen}
                  className="grid h-8 w-8 place-items-center rounded-lg border border-border bg-background/50 text-muted-foreground transition hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
                >
                  <Maximize2 className="h-3.5 w-3.5" aria-hidden="true" />
                </button>
              )}
              {tableVisible && (
                <div className="relative shrink-0">
                  <label htmlFor={searchId} className="sr-only">
                    {tr.sqlTable.searchRows}
                  </label>
                  <Search
                    className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
                    aria-hidden="true"
                  />
                  <input
                    id={searchId}
                    type="search"
                    value={query}
                    onChange={(e) => {
                      setQuery(e.target.value);
                      setPage(1);
                    }}
                    placeholder={tr.sqlTable.searchRows}
                    aria-controls={tableId}
                    className="h-8 w-40 rounded-lg border border-border bg-background/50 pl-8 pr-2 text-xs placeholder:text-muted-foreground/70 focus-visible:border-primary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
                  />
                </div>
              )}
            </div>
          </div>

          {truncationNotice && (
            <div
              role="status"
              className="mt-2 flex items-start gap-2 rounded-md border border-warning/35 bg-warning/10 px-3 py-2 text-[11px] text-foreground"
            >
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
              <span>{truncationNotice}</span>
            </div>
          )}

          {tableVisible && (
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    type="button"
                    aria-label={tr.sqlTable.manageColumns}
                    className="flex h-8 items-center gap-1.5 rounded-lg border border-border bg-background/50 px-2.5 text-xs font-medium text-muted-foreground transition hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
                  >
                    <Settings2 className="h-3.5 w-3.5" aria-hidden="true" />
                    {tr.sqlTable.columns}
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-48">
                  <div className="max-h-60 overflow-auto p-1">
                    {data.columns.map((c) => (
                      <DropdownMenuItem
                        key={c}
                        onSelect={(e: Event) => {
                          e.preventDefault();
                          toggleColumnVisibility(c);
                        }}
                        className="flex cursor-pointer items-center gap-2"
                      >
                        <Checkbox checked={columnVisibility[c]} aria-hidden="true" />
                        <span className="truncate text-xs" title={columnLabel(c)}>
                          {columnLabel(c)}
                        </span>
                      </DropdownMenuItem>
                    ))}
                  </div>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onSelect={showAllColumns} className="text-xs">
                    {tr.sqlTable.showAllColumns}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>

              <button
                type="button"
                onClick={cycleDensity}
                aria-label={tr.sqlTable.changeDensity}
                title={`${tr.sqlTable.density}: ${tr.sqlTable.densities[density]}`}
                className="grid h-8 w-8 place-items-center rounded-lg border border-border bg-background/50 text-muted-foreground transition hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
              >
                <Rows3 className="h-3.5 w-3.5" aria-hidden="true" />
              </button>

              <button
                type="button"
                onClick={copyTable}
                aria-label={tr.sqlTable.copyTable}
                className="flex h-8 items-center gap-1.5 rounded-lg border border-border bg-background/50 px-2.5 text-xs font-medium text-muted-foreground transition hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
              >
                {copied ? (
                  <Check className="h-3.5 w-3.5 text-success" aria-hidden="true" />
                ) : (
                  <Copy className="h-3.5 w-3.5" aria-hidden="true" />
                )}
                {tr.sqlTable.copy}
              </button>

              <button
                type="button"
                onClick={() => setShowStats((v) => !v)}
                aria-pressed={showStats}
                aria-label={tr.sqlTable.toggleStats}
                className={cn(
                  "flex h-8 items-center gap-1.5 rounded-lg border border-border px-2.5 text-xs font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60",
                  showStats
                    ? "bg-primary/15 text-primary"
                    : "bg-background/50 text-muted-foreground hover:bg-accent hover:text-foreground",
                )}
              >
                <Sigma className="h-3.5 w-3.5" aria-hidden="true" />
                {tr.sqlTable.stats}
              </button>
              <button
                type="button"
                onClick={() => setShowChart((v) => !v)}
                aria-pressed={showChart}
                aria-label={tr.sqlTable.toggleChart}
                className={cn(
                  "flex h-8 items-center gap-1.5 rounded-lg border border-border px-2.5 text-xs font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60",
                  showChart
                    ? "bg-primary/15 text-primary"
                    : "bg-background/50 text-muted-foreground hover:bg-accent hover:text-foreground",
                )}
              >
                <BarChart3 className="h-3.5 w-3.5" aria-hidden="true" />
                {tr.sqlTable.chart}
              </button>

              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    type="button"
                    aria-label={tr.sqlTable.exportResults}
                    className="flex h-8 items-center gap-1.5 rounded-lg bg-primary/15 px-2.5 text-xs font-medium text-primary transition hover:bg-primary/25 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
                  >
                    <Download className="h-3.5 w-3.5" aria-hidden="true" />
                    {tr.sqlTable.export}
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-52">
                  <DropdownMenuItem onSelect={() => exportAll("csv")} className="gap-2 text-xs">
                    <Download className="h-3.5 w-3.5" />
                    {tr.sqlTable.exportCsv}
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => exportAll("json")} className="gap-2 text-xs">
                    <FileJson className="h-3.5 w-3.5" />
                    {tr.sqlTable.exportJson}
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <div className="px-2 py-1.5">
                    <label className="mb-1 block text-[10px] uppercase tracking-wide text-muted-foreground">
                      {tr.sqlTable.tableName}
                    </label>
                    <Input
                      value={sqlTableName}
                      onChange={(e) => setSqlTableName(e.target.value)}
                      className="h-7 text-xs"
                      placeholder="sonuclar"
                      onClick={(e) => e.stopPropagation()}
                    />
                  </div>
                  <DropdownMenuItem onSelect={() => exportAll("sql")} className="gap-2 text-xs">
                    <FileCode className="h-3.5 w-3.5" />
                    {tr.sqlTable.exportSql}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          )}
        </div>

        {/* Active filters bar */}
        {hasActiveFilters && (
          <div className="flex flex-wrap items-center gap-1.5 border-b border-border/40 bg-background/30 px-3 py-2">
            <Filter className="h-3 w-3 text-muted-foreground" aria-hidden="true" />
            {filters.map((f) => (
              <span
                key={f.id}
                className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[11px] text-primary"
              >
                {columnLabel(f.column)} {tr.sqlTable.operators[f.operator]} {f.value}
                <button
                  type="button"
                  onClick={() => removeFilter(f.id)}
                  aria-label={tr.sqlTable.removeFilter(f.column)}
                  className="rounded-full p-0.5 hover:bg-primary/20"
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
            {query.trim() && (
              <span className="inline-flex items-center gap-1 rounded-full bg-accent/40 px-2 py-0.5 text-[11px] text-muted-foreground">
                {tr.sqlTable.searchFilter(query)}
              </span>
            )}
            <button
              type="button"
              onClick={clearFilters}
              className="ml-auto text-[11px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
            >
              {tr.sqlTable.clearAllFilters}
            </button>
          </div>
        )}

        {/* Bulk selection bar */}
        {selectedRows.size > 0 && (
          <div className="flex items-center justify-between gap-2 border-b border-border/40 bg-primary/10 px-3 py-2">
            <div className="flex items-center gap-2 text-xs text-primary">
              <ListChecks className="h-3.5 w-3.5" aria-hidden="true" />
              <span className="font-medium">{tr.sqlTable.selectedRows(selectedRows.size)}</span>
            </div>
            <div className="flex items-center gap-1.5">
              <Button
                variant="ghost"
                size="sm"
                onClick={copySelected}
                className="h-7 gap-1 text-xs"
              >
                <Copy className="h-3.5 w-3.5" />
                {tr.sqlTable.copy}
              </Button>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="sm" className="h-7 gap-1 text-xs">
                    <Download className="h-3.5 w-3.5" />
                    {tr.sqlTable.export}
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onSelect={() => exportSelected("csv")} className="text-xs">
                    CSV
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => exportSelected("json")} className="text-xs">
                    JSON
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => exportSelected("sql")} className="text-xs">
                    SQL INSERT
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
              <Button
                variant="ghost"
                size="sm"
                onClick={clearSelection}
                className="h-7 gap-1 text-xs text-destructive hover:text-destructive"
              >
                <Trash2 className="h-3.5 w-3.5" />
                {tr.sqlTable.clearSelection}
              </Button>
            </div>
          </div>
        )}

        <AnimatePresence initial={false}>
          {showStats && (
            <motion.div
              key="stats"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={uiTransition}
              className="overflow-hidden"
            >
              <SqlSummaryStats columns={visibleColumns} rows={sorted.map((m) => m.row)} />
            </motion.div>
          )}
          {showChart && (
            <motion.div
              key="chart"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={uiTransition}
              className="overflow-hidden"
            >
              {showScalarMetricPanel ? (
                <div className="border-b border-border/40 bg-background/20 px-4 py-4">
                  <div className="mb-3 flex min-w-0 items-center justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-xs font-semibold text-foreground">
                        {tr.sqlChart.scalarMetricTitle}
                      </p>
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        {tr.sqlChart.scalarMetricDescription}
                      </p>
                    </div>
                  </div>
                  <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                    {scalarMetricCards.map((card) => (
                      <div
                        key={`${card.context ?? "scalar"}-${card.label}`}
                        className="min-w-0 rounded-lg border border-border/60 bg-background/55 px-4 py-3"
                      >
                        <div
                          className={cn(
                            "line-clamp-2 break-words font-semibold [overflow-wrap:anywhere]",
                            Array.from(card.value).length > 18
                              ? "text-lg leading-6"
                              : "text-2xl leading-7",
                            card.isEmpty ? "text-muted-foreground" : "text-foreground",
                          )}
                          title={card.value}
                        >
                          {card.value}
                        </div>
                        <div
                          className="mt-2 line-clamp-2 break-words text-[11px] font-medium leading-4 text-muted-foreground [overflow-wrap:anywhere]"
                          title={card.label}
                        >
                          {card.label}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <Suspense fallback={<div className="h-72 animate-pulse bg-muted/20" />}>
                  <LazySqlChartPanel
                    columns={visibleColumns}
                    rows={sorted.map((item) => item.row)}
                    initialType={recommendedChartType ?? undefined}
                    onCategorySelect={(column, value) => addFilter(column, "eq", value)}
                  />
                </Suspense>
              )}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Table */}
        {tableVisible &&
          (isVirtualized ? (
            <div
              ref={scrollRef}
              role="region"
              aria-label={tr.sqlTable.scrollableResults}
              tabIndex={-1}
              className="overflow-auto"
              style={{ maxHeight: virtualHeight }}
            >
              <table
                id={tableId}
                className="w-full text-xs"
                role="table"
                aria-rowcount={sorted.length}
                aria-colcount={visibleColumns.length + 1}
                style={{ tableLayout: "fixed" }}
              >
                <caption className="sr-only">
                  {tr.sqlTable.captionVirtual(sorted.length, visibleColumns.length)}
                </caption>
                <thead className="sticky top-0 z-10 bg-background/80 backdrop-blur">
                  {headerRow}
                </thead>
                <tbody
                  style={{
                    display: "block",
                    position: "relative",
                    height: virtualizer.getTotalSize(),
                  }}
                >
                  {virtualizer.getVirtualItems().map((v) => {
                    const meta = sorted[v.index];
                    const isFocused = focusedRow === v.index;
                    return (
                      <tr
                        key={v.key}
                        id={`${tableId}-row-${v.index}`}
                        data-index={v.index}
                        role="button"
                        tabIndex={0}
                        aria-rowindex={v.index + 1}
                        aria-label={tr.sqlTable.viewRowDetails(v.index + 1)}
                        onClick={() => openRow(v.index)}
                        onFocus={() => setFocusedRow(v.index)}
                        onKeyDown={(e) => onRowKeyDown(e, v.index, v.index)}
                        style={{
                          position: "absolute",
                          top: 0,
                          left: 0,
                          width: "100%",
                          height: v.size,
                          transform: `translateY(${v.start}px)`,
                          display: "table",
                          tableLayout: "fixed",
                        }}
                        className={cn(
                          "cursor-pointer transition hover:bg-primary/5 focus-visible:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary/60",
                          isFocused && "bg-primary/5",
                        )}
                      >
                        <td
                          className={cn(
                            "sticky left-0 z-[1] w-16 min-w-16 border-b border-border/40 bg-background/95 px-2 backdrop-blur",
                            cellPadding,
                          )}
                        >
                          <div className="flex items-center justify-between gap-1">
                            <Checkbox
                              checked={selectedRows.has(meta.idx)}
                              aria-label={tr.sqlTable.selectRow(v.index + 1)}
                              onCheckedChange={() => toggleSelectRow(meta.idx)}
                              onClick={(e) => e.stopPropagation()}
                            />
                            <span
                              aria-hidden="true"
                              className="font-mono text-[10px] text-muted-foreground/70"
                            >
                              {v.index + 1}
                            </span>
                          </div>
                        </td>
                        {renderCells(meta)}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table
                id={tableId}
                className="w-full text-xs"
                role="table"
                aria-rowcount={sorted.length}
                aria-colcount={visibleColumns.length + 1}
                style={{ tableLayout: "fixed" }}
              >
                <caption className="sr-only">
                  {tr.sqlTable.caption(sorted.length, visibleColumns.length)}
                </caption>
                <thead>{headerRow}</thead>
                <tbody>
                  {pageRows.length === 0 ? (
                    <tr>
                      <td
                        colSpan={visibleColumns.length + 1}
                        className="px-3 py-8 text-center text-xs text-muted-foreground"
                      >
                        {tr.sqlTable.noMatchingRows}
                      </td>
                    </tr>
                  ) : (
                    pageRows.map((meta, i) => {
                      const absIdx = (safePage - 1) * safePageSize + i;
                      return (
                        <tr
                          key={i}
                          ref={(el) => {
                            rowRefs.current[i] = el;
                          }}
                          role="button"
                          tabIndex={0}
                          aria-label={tr.sqlTable.viewRowDetails(absIdx + 1)}
                          onClick={() => openRow(absIdx)}
                          onKeyDown={(e) => onRowKeyDown(e, i, absIdx)}
                          className="cursor-pointer transition hover:bg-primary/5 focus-visible:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary/60"
                        >
                          <td
                            className={cn(
                              "sticky left-0 z-[1] w-16 min-w-16 border-b border-border/40 bg-background/95 px-2 backdrop-blur",
                              cellPadding,
                            )}
                          >
                            <div className="flex items-center justify-between gap-1">
                              <Checkbox
                                checked={selectedRows.has(meta.idx)}
                                aria-label={tr.sqlTable.selectRow(absIdx + 1)}
                                onCheckedChange={() => toggleSelectRow(meta.idx)}
                                onClick={(e) => e.stopPropagation()}
                              />
                              <span
                                aria-hidden="true"
                                className="font-mono text-[10px] text-muted-foreground/70"
                              >
                                {absIdx + 1}
                              </span>
                            </div>
                          </td>
                          {renderCells(meta)}
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          ))}

        {/* Footer / Pagination */}
        {tableVisible &&
          (isVirtualized ? (
            <div className="flex items-center justify-between gap-2 border-t border-border/60 px-3 py-2 text-[11px] text-muted-foreground">
              <div>
                <span className="font-medium text-foreground">
                  {sorted.length.toLocaleString()}
                </span>{" "}
                {tr.sqlTable.scrollToLoadMore}
              </div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground/70">
                {tr.sqlTable.virtualizedRendering}
              </div>
            </div>
          ) : (
            <nav
              aria-label={tr.sqlTable.pagination}
              className="flex items-center justify-between gap-2 border-t border-border/60 px-3 py-2 text-[11px] text-muted-foreground"
            >
              <div>
                {tr.sqlTable.showing}{" "}
                <span className="font-medium text-foreground">
                  {sorted.length === 0 ? 0 : (safePage - 1) * safePageSize + 1}–
                  {Math.min(safePage * safePageSize, sorted.length)}
                </span>{" "}
                {tr.sqlTable.of}{" "}
                <span className="font-medium text-foreground">{sorted.length}</span>
              </div>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  disabled={safePage <= 1}
                  aria-disabled={safePage <= 1}
                  aria-label={tr.sqlTable.previousPage}
                  onClick={goPrev}
                  className="flex h-7 items-center gap-1 rounded-md border border-border bg-background/50 px-2 text-muted-foreground transition hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <ChevronLeft className="h-3.5 w-3.5" aria-hidden="true" />
                  <span>{tr.sqlTable.previous}</span>
                </button>
                <div className="px-2 text-foreground" aria-live="polite">
                  {tr.sqlTable.page} {safePage}
                  <span aria-hidden="true"> / </span>
                  <span className="sr-only"> {tr.sqlTable.of} </span>
                  {totalPages}
                </div>
                <button
                  type="button"
                  disabled={safePage >= totalPages}
                  aria-disabled={safePage >= totalPages}
                  aria-label={tr.sqlTable.nextPage}
                  onClick={goNext}
                  className="flex h-7 items-center gap-1 rounded-md border border-border bg-background/50 px-2 text-muted-foreground transition hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <span>{tr.sqlTable.next}</span>
                  <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
                </button>
              </div>
            </nav>
          ))}

        <SqlRowDrawer
          open={drawerOpen}
          onOpenChange={setDrawerOpen}
          columns={visibleColumns}
          row={selectedRow}
          rowIndex={selectedIndex}
          totalRows={sorted.length}
        />
      </div>
      {allowFullscreen && (
        <Dialog open={fullscreenOpen} onOpenChange={setFullscreenOpen}>
          <DialogContent className="h-[calc(100vh-3rem)] max-w-[calc(100vw-3rem)] gap-0 overflow-hidden p-0">
            <DialogHeader className="shrink-0 border-b border-border px-5 py-4">
              <DialogTitle className="text-base">{tr.sqlTable.fullscreenTitle}</DialogTitle>
              <DialogDescription className="text-xs">
                {tr.sqlTable.fullscreenDescription}
              </DialogDescription>
            </DialogHeader>
            <div className="min-h-0 overflow-auto p-3">
              <SqlResultsTable
                data={data}
                pageSize={Math.max(safePageSize, 12)}
                displayMode={displayMode}
                virtualizeThreshold={virtualizeThreshold}
                rowHeight={rowHeight}
                virtualHeight={Math.max(virtualHeight, 560)}
                allowFullscreen={false}
              />
            </div>
          </DialogContent>
        </Dialog>
      )}
    </>
  );
}

function makeId() {
  return Math.random().toString(36).slice(2, 10);
}

function FilterPopover({
  label,
  onApply,
  existing,
  onClear,
}: {
  /** Türkçe display label; the raw column key is captured by `onApply`'s closure. */
  label: string;
  onApply: (operator: FilterOperator, value: string) => void;
  existing?: FilterRule;
  onClear: () => void;
}) {
  const [operator, setOperator] = useState<FilterOperator>(existing?.operator ?? "contains");
  const [value, setValue] = useState(existing?.value ?? "");
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (existing) {
      setOperator(existing.operator);
      setValue(existing.value);
    } else {
      setOperator("contains");
      setValue("");
    }
  }, [existing, open]);

  const needsValue = operator !== "empty" && operator !== "notEmpty";

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={tr.sqlTable.filterColumn(label)}
          className={cn(
            "mr-1 rounded p-1 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60",
            existing ? "bg-primary/15 text-primary" : "text-muted-foreground hover:text-foreground",
          )}
        >
          <Filter className="h-3 w-3" />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-56 p-3" align="end">
        <div className="mb-2 text-xs font-semibold text-foreground">
          {tr.sqlTable.filterTitle(label)}
        </div>
        <Select value={operator} onValueChange={(v) => setOperator(v as FilterOperator)}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="eq">{tr.sqlTable.operators.eq}</SelectItem>
            <SelectItem value="contains">{tr.sqlTable.operators.contains}</SelectItem>
            <SelectItem value="gt">{tr.sqlTable.operators.gt}</SelectItem>
            <SelectItem value="lt">{tr.sqlTable.operators.lt}</SelectItem>
            <SelectItem value="gte">{tr.sqlTable.operators.gte}</SelectItem>
            <SelectItem value="lte">{tr.sqlTable.operators.lte}</SelectItem>
            <SelectItem value="empty">{tr.sqlTable.operators.empty}</SelectItem>
            <SelectItem value="notEmpty">{tr.sqlTable.operators.notEmpty}</SelectItem>
          </SelectContent>
        </Select>
        {needsValue && (
          <Input
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder={tr.sqlTable.filterValue}
            className="mt-2 h-8 text-xs"
          />
        )}
        <div className="mt-3 flex items-center gap-2">
          <Button
            size="sm"
            className="h-7 flex-1 text-xs"
            onClick={() => {
              onApply(operator, value);
              setOpen(false);
            }}
          >
            {tr.sqlTable.applyFilter}
          </Button>
          {existing && (
            <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={onClear}>
              {tr.sqlTable.clearFilter}
            </Button>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
