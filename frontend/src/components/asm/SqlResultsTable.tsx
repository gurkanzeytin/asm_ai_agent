import { useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
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
} from "lucide-react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import { SqlRowDrawer } from "./SqlRowDrawer";

export interface SqlResult {
  columns: string[];
  rows: Array<Record<string, string | number | null>>;
  query?: string;
  durationMs?: number;
}

interface Props {
  data: SqlResult;
  pageSize?: number;
  /** Switch to virtualized scrolling above this row count. Default 100. */
  virtualizeThreshold?: number;
  /** Approx row height in px for the virtualizer. */
  rowHeight?: number;
  /** Max viewport height for virtualized scroll area. */
  virtualHeight?: number;
}

type SortDir = "asc" | "desc" | null;

export function SqlResultsTable({
  data,
  pageSize = 8,
  virtualizeThreshold = 100,
  rowHeight = 32,
  virtualHeight = 420,
}: Props) {
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>(null);
  const [page, setPage] = useState(1);
  const [copied, setCopied] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [focusedRow, setFocusedRow] = useState<number | null>(null);

  const tableId = useId();
  const searchId = useId();
  const rowRefs = useRef<Array<HTMLTableRowElement | null>>([]);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return data.rows;
    return data.rows.filter((r) =>
      data.columns.some((c) => String(r[c] ?? "").toLowerCase().includes(q))
    );
  }, [data, query]);

  const sorted = useMemo(() => {
    if (!sortKey || !sortDir) return filtered;
    const dir = sortDir === "asc" ? 1 : -1;
    return [...filtered].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
      return String(av).localeCompare(String(bv), undefined, { numeric: true }) * dir;
    });
  }, [filtered, sortKey, sortDir]);

  const isVirtualized = sorted.length > virtualizeThreshold;
  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const pageRows = isVirtualized ? sorted : sorted.slice((safePage - 1) * pageSize, safePage * pageSize);

  const virtualizer = useVirtualizer({
    count: isVirtualized ? sorted.length : 0,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => rowHeight,
    overscan: 10,
  });

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
      nextKey && nextDir
        ? `Sorted by ${col} ${nextDir === "asc" ? "ascending" : "descending"}`
        : "Sort cleared"
    );
  };

  const ariaSortFor = (col: string): "ascending" | "descending" | "none" => {
    if (sortKey !== col || !sortDir) return "none";
    return sortDir === "asc" ? "ascending" : "descending";
  };

  const toCsv = (rows: typeof sorted) => {
    const escape = (v: unknown) => {
      const s = v == null ? "" : String(v);
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const header = data.columns.map(escape).join(",");
    const body = rows.map((r) => data.columns.map((c) => escape(r[c])).join(",")).join("\n");
    return `${header}\n${body}`;
  };

  const exportCsv = () => {
    const csv = toCsv(sorted);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `sql-results-${Date.now()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success("CSV exported", { description: `${sorted.length} rows` });
    setAnnouncement(`Exported ${sorted.length} rows as CSV`);
  };

  const copyTable = async () => {
    const tsv = [
      data.columns.join("\t"),
      ...sorted.map((r) => data.columns.map((c) => r[c] ?? "").join("\t")),
    ].join("\n");
    try {
      await navigator.clipboard.writeText(tsv);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
      toast.success("Table copied", { description: "Paste into a spreadsheet or doc." });
      setAnnouncement("Table copied to clipboard");
    } catch {
      toast.error("Copy failed");
      setAnnouncement("Copy failed");
    }
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
    // Focus after next paint so the row is mounted
    requestAnimationFrame(() => {
      const el = document.getElementById(`${tableId}-row-${clamped}`);
      if (el) (el as HTMLElement).focus();
    });
  };

  const onRowKeyDown = (
    e: KeyboardEvent<HTMLTableRowElement>,
    localIdx: number,
    absIdx: number
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
      setAnnouncement(`Page ${safePage - 1} of ${totalPages}`);
    }
  };
  const goNext = () => {
    if (safePage < totalPages) {
      setPage((p) => Math.min(totalPages, p + 1));
      setAnnouncement(`Page ${safePage + 1} of ${totalPages}`);
    }
  };

  const selectedRow = selectedIndex != null ? sorted[selectedIndex] ?? null : null;

  // Shared cell renderer to keep classic + virtual rows visually identical.
  const renderCells = (r: Record<string, string | number | null>) =>
    data.columns.map((c) => (
      <td
        key={c}
        className="border-b border-border/40 px-3 py-2 font-mono text-[11.5px] text-foreground/90"
      >
        {r[c] == null ? (
          <span className="text-muted-foreground/60">NULL</span>
        ) : (
          String(r[c])
        )}
      </td>
    ));

  const headerRow = (
    <tr className="bg-background/30">
      {data.columns.map((col) => {
        const isActive = sortKey === col;
        const Icon = !isActive ? ArrowUpDown : sortDir === "asc" ? ArrowUp : ArrowDown;
        const nextLabel = !isActive
          ? "ascending"
          : sortDir === "asc"
          ? "descending"
          : "clear sort";
        return (
          <th
            key={col}
            scope="col"
            aria-sort={ariaSortFor(col)}
            className="border-b border-border/60 p-0 text-left font-semibold text-muted-foreground"
          >
            <button
              type="button"
              onClick={() => toggleSort(col)}
              aria-label={`Sort by ${col}, ${
                isActive ? `currently ${sortDir === "asc" ? "ascending" : "descending"}, ` : ""
              }activate to sort ${nextLabel}`}
              className="inline-flex w-full items-center gap-1.5 px-3 py-2.5 text-left transition hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary/60"
            >
              {col}
              <Icon
                aria-hidden="true"
                className={cn(
                  "h-3 w-3 transition",
                  isActive ? "text-primary" : "text-muted-foreground/50"
                )}
              />
            </button>
          </th>
        );
      })}
    </tr>
  );

  return (
    <div className="glass mt-3 overflow-hidden rounded-2xl">
      <span className="sr-only" aria-live="polite" aria-atomic="true">
        {announcement}
      </span>

      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2 border-b border-border/60 px-3 py-2.5">
        <div className="flex items-center gap-2 pr-2 text-xs font-semibold text-muted-foreground">
          <Database className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
          <span>SQL Result</span>
          <span className="rounded-full bg-primary/15 px-2 py-0.5 text-[10px] font-semibold text-primary">
            {sorted.length} rows
          </span>
          {isVirtualized && (
            <span
              className="rounded-full bg-accent/40 px-2 py-0.5 text-[10px] font-semibold text-muted-foreground"
              title="Row virtualization is active for fast scrolling"
            >
              virtualized
            </span>
          )}
          {data.durationMs != null && (
            <span className="text-[11px] font-normal text-muted-foreground/80">
              · {data.durationMs}ms
            </span>
          )}
        </div>
        <div className="relative ml-auto">
          <label htmlFor={searchId} className="sr-only">
            Search rows
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
            placeholder="Search rows"
            aria-controls={tableId}
            className="h-8 w-40 rounded-lg border border-border bg-background/50 pl-8 pr-2 text-xs placeholder:text-muted-foreground/70 focus-visible:border-primary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
          />
        </div>
        <button
          type="button"
          onClick={copyTable}
          aria-label="Copy table to clipboard"
          className="flex h-8 items-center gap-1.5 rounded-lg border border-border bg-background/50 px-2.5 text-xs font-medium text-muted-foreground transition hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
        >
          {copied ? (
            <Check className="h-3.5 w-3.5 text-success" aria-hidden="true" />
          ) : (
            <Copy className="h-3.5 w-3.5" aria-hidden="true" />
          )}
          Copy
        </button>
        <button
          type="button"
          onClick={exportCsv}
          aria-label="Export results as CSV"
          className="flex h-8 items-center gap-1.5 rounded-lg bg-primary/15 px-2.5 text-xs font-medium text-primary transition hover:bg-primary/25 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
        >
          <Download className="h-3.5 w-3.5" aria-hidden="true" />
          Export CSV
        </button>
      </div>

      {/* Table */}
      {isVirtualized ? (
        <div
          ref={scrollRef}
          role="region"
          aria-label="Scrollable results"
          tabIndex={-1}
          className="overflow-auto"
          style={{ maxHeight: virtualHeight }}
        >
          <table
            id={tableId}
            className="w-full text-xs"
            role="table"
            aria-rowcount={sorted.length}
            aria-colcount={data.columns.length}
          >
            <caption className="sr-only">
              SQL results table with {sorted.length} rows and {data.columns.length} columns.
              Virtualized. Use arrow keys, PageUp/PageDown, Home/End to move; Enter opens details.
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
                const r = sorted[v.index];
                const isFocused = focusedRow === v.index;
                return (
                  <tr
                    key={v.key}
                    id={`${tableId}-row-${v.index}`}
                    data-index={v.index}
                    role="button"
                    tabIndex={0}
                    aria-rowindex={v.index + 1}
                    aria-label={`View details for row ${v.index + 1}`}
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
                      isFocused && "bg-primary/5"
                    )}
                  >
                    {renderCells(r)}
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
            aria-colcount={data.columns.length}
          >
            <caption className="sr-only">
              SQL results table with {sorted.length} rows and {data.columns.length} columns. Use
              arrow keys to move between rows. Press Enter to view full row details.
            </caption>
            <thead>{headerRow}</thead>
            <tbody>
              {pageRows.length === 0 ? (
                <tr>
                  <td
                    colSpan={data.columns.length}
                    className="px-3 py-8 text-center text-xs text-muted-foreground"
                  >
                    No matching rows
                  </td>
                </tr>
              ) : (
                pageRows.map((r, i) => {
                  const absIdx = (safePage - 1) * pageSize + i;
                  return (
                    <tr
                      key={i}
                      ref={(el) => {
                        rowRefs.current[i] = el;
                      }}
                      role="button"
                      tabIndex={0}
                      aria-label={`View details for row ${absIdx + 1}`}
                      onClick={() => openRow(absIdx)}
                      onKeyDown={(e) => onRowKeyDown(e, i, absIdx)}
                      className="cursor-pointer transition hover:bg-primary/5 focus-visible:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary/60"
                    >
                      {renderCells(r)}
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Footer / Pagination */}
      {isVirtualized ? (
        <div className="flex items-center justify-between gap-2 border-t border-border/60 px-3 py-2 text-[11px] text-muted-foreground">
          <div>
            <span className="font-medium text-foreground">{sorted.length.toLocaleString()}</span>{" "}
            rows · scroll to load more
          </div>
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground/70">
            Virtualized rendering
          </div>
        </div>
      ) : (
        <nav
          aria-label="Table pagination"
          className="flex items-center justify-between gap-2 border-t border-border/60 px-3 py-2 text-[11px] text-muted-foreground"
        >
          <div>
            Showing{" "}
            <span className="font-medium text-foreground">
              {sorted.length === 0 ? 0 : (safePage - 1) * pageSize + 1}
              –{Math.min(safePage * pageSize, sorted.length)}
            </span>{" "}
            of <span className="font-medium text-foreground">{sorted.length}</span>
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              disabled={safePage <= 1}
              aria-disabled={safePage <= 1}
              aria-label="Previous page"
              onClick={goPrev}
              className="grid h-7 w-7 place-items-center rounded-md border border-border bg-background/50 text-muted-foreground transition hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <ChevronLeft className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
            <div className="px-2 text-foreground" aria-live="polite">
              <span className="sr-only">Page </span>
              {safePage}
              <span aria-hidden="true"> / </span>
              <span className="sr-only"> of </span>
              {totalPages}
            </div>
            <button
              type="button"
              disabled={safePage >= totalPages}
              aria-disabled={safePage >= totalPages}
              aria-label="Next page"
              onClick={goNext}
              className="grid h-7 w-7 place-items-center rounded-md border border-border bg-background/50 text-muted-foreground transition hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          </div>
        </nav>
      )}

      <SqlRowDrawer
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        columns={data.columns}
        row={selectedRow}
        rowIndex={selectedIndex}
        totalRows={sorted.length}
      />
    </div>
  );
}
