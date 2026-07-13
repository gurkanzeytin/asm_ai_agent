import { useState } from "react";
import { Copy, Check, ClipboardList } from "lucide-react";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { toast } from "sonner";

type RowValue = string | number | null;

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  columns: string[];
  row: Record<string, RowValue> | null;
  rowIndex: number | null;
  totalRows: number;
}

function formatValue(v: RowValue): { display: string; isJson: boolean; isNull: boolean } {
  if (v == null) return { display: "NULL", isJson: false, isNull: true };
  const s = String(v);
  const trimmed = s.trim();
  if (
    (trimmed.startsWith("{") && trimmed.endsWith("}")) ||
    (trimmed.startsWith("[") && trimmed.endsWith("]"))
  ) {
    try {
      return { display: JSON.stringify(JSON.parse(trimmed), null, 2), isJson: true, isNull: false };
    } catch {
      /* not JSON */
    }
  }
  return { display: s, isJson: false, isNull: false };
}

export function SqlRowDrawer({ open, onOpenChange, columns, row, rowIndex, totalRows }: Props) {
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  const copy = async (key: string, value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopiedKey(key);
      setTimeout(() => setCopiedKey((k) => (k === key ? null : k)), 1200);
      toast.success("Copied", { description: key });
    } catch {
      toast.error("Copy failed");
    }
  };

  const copyRowJson = async () => {
    if (!row) return;
    const obj = Object.fromEntries(columns.map((c) => [c, row[c] ?? null]));
    await copy("__row__", JSON.stringify(obj, null, 2));
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="w-full border-l border-border/60 bg-background/95 backdrop-blur sm:max-w-lg"
      >
        <SheetHeader className="space-y-1">
          <SheetTitle className="text-base font-semibold">
            Row {rowIndex != null ? rowIndex + 1 : ""} details
          </SheetTitle>
          <SheetDescription>
            {rowIndex != null
              ? `Viewing row ${rowIndex + 1} of ${totalRows}. Press Escape to close.`
              : "No row selected."}
          </SheetDescription>
          <div className="pt-2">
            <button
              type="button"
              onClick={copyRowJson}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-background/50 px-2.5 py-1.5 text-xs font-medium text-muted-foreground transition hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
              aria-label="Copy entire row as JSON"
            >
              {copiedKey === "__row__" ? (
                <Check className="h-3.5 w-3.5 text-success" />
              ) : (
                <ClipboardList className="h-3.5 w-3.5" />
              )}
              Copy row as JSON
            </button>
          </div>
        </SheetHeader>

        <div className="mt-4 max-h-[calc(100dvh-10rem)] space-y-3 overflow-y-auto pr-1">
          {row &&
            columns.map((col) => {
              const { display, isJson, isNull } = formatValue(row[col]);
              return (
                <div
                  key={col}
                  className="rounded-xl border border-border/60 bg-background/40 p-3"
                >
                  <div className="mb-1.5 flex items-center justify-between gap-2">
                    <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                      {col}
                    </div>
                    <button
                      type="button"
                      onClick={() => copy(col, display)}
                      aria-label={`Copy value of ${col}`}
                      className="inline-flex items-center gap-1 rounded-md border border-border bg-background/50 px-2 py-1 text-[10.5px] font-medium text-muted-foreground transition hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
                    >
                      {copiedKey === col ? (
                        <Check className="h-3 w-3 text-success" />
                      ) : (
                        <Copy className="h-3 w-3" />
                      )}
                      Copy
                    </button>
                  </div>
                  {isNull ? (
                    <div className="font-mono text-xs text-muted-foreground/60">NULL</div>
                  ) : (
                    <pre className="whitespace-pre-wrap break-words font-mono text-[12px] leading-relaxed text-foreground/90">
                      {display}
                    </pre>
                  )}
                  {isJson && (
                    <div className="mt-1 text-[10px] uppercase tracking-wide text-primary/70">
                      JSON
                    </div>
                  )}
                </div>
              );
            })}
        </div>
      </SheetContent>
    </Sheet>
  );
}
