import { useState, type ReactNode } from "react";
import { Check, Copy, Database } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { tr } from "@/locales/tr";

// Lightweight, dependency-free SQL syntax highlighter. Single-pass tokenizer:
// comments and strings win first (so a keyword inside a string is not
// recoloured), then keywords / functions / numbers. Unmatched text is emitted
// verbatim, so unknown identifiers (column/table names) keep the base colour.
const SQL_TOKEN =
  /(--[^\n]*|\/\*[\s\S]*?\*\/)|('(?:[^']|'')*')|\b(SELECT|FROM|WHERE|GROUP|ORDER|BY|HAVING|JOIN|LEFT|RIGHT|INNER|OUTER|FULL|CROSS|APPLY|ON|AND|OR|NOT|IN|AS|CASE|WHEN|THEN|ELSE|END|DISTINCT|TOP|PERCENT|OVER|PARTITION|DESC|ASC|BETWEEN|LIKE|IS|NULL|WITH|UNION|ALL|EXISTS)\b|\b(COUNT|SUM|AVG|MIN|MAX|NULLIF|DATEDIFF|DATEADD|CAST|CONVERT|LTRIM|RTRIM|REPLACE|COALESCE|ROW_NUMBER|RANK|ABS|YEAR|MONTH|DAY|GETDATE)\b|\b(\d+(?:\.\d+)?)\b/gi;

function highlightSql(sql: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let key = 0;
  let match: RegExpExecArray | null;
  SQL_TOKEN.lastIndex = 0;
  while ((match = SQL_TOKEN.exec(sql)) !== null) {
    if (match.index > last) out.push(sql.slice(last, match.index));
    const [full, comment, str, keyword, fn, num] = match;
    if (comment) {
      out.push(
        <span key={key++} className="italic text-muted-foreground">
          {full}
        </span>,
      );
    } else if (str) {
      out.push(
        <span key={key++} className="text-[color:var(--success)]">
          {full}
        </span>,
      );
    } else if (keyword) {
      out.push(
        <span key={key++} className="font-semibold text-primary">
          {full}
        </span>,
      );
    } else if (fn) {
      out.push(
        <span key={key++} className="text-[color:var(--cyan)]">
          {full}
        </span>,
      );
    } else if (num) {
      out.push(
        <span key={key++} className="text-[color:var(--warning)]">
          {full}
        </span>,
      );
    } else {
      out.push(full);
    }
    last = match.index + full.length;
  }
  if (last < sql.length) out.push(sql.slice(last));
  return out;
}

interface Props {
  sql: string;
  /** Show the header bar (label + copy). Off for inline/compact renders. */
  header?: boolean;
  className?: string;
  preClassName?: string;
}

export function SqlCode({ sql, header = true, className, preClassName }: Props) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error(tr.common.copyFailed);
    }
  };

  return (
    <div
      className={cn(
        "my-2 min-w-0 max-w-full overflow-hidden rounded-xl border border-border",
        className,
      )}
    >
      {header && (
        <div className="flex items-center justify-between border-b border-border bg-muted px-3 py-1.5">
          <span className="flex items-center gap-1.5 text-[11px] font-semibold text-muted-foreground">
            <Database className="h-3.5 w-3.5" aria-hidden="true" />
            {tr.details.sqlModalTitle}
          </span>
          <button
            type="button"
            onClick={copy}
            title={tr.details.copySql}
            aria-label={tr.details.copySql}
            className="grid h-6 w-6 place-items-center rounded-md text-muted-foreground transition hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
          >
            {copied ? (
              <Check className="h-3.5 w-3.5 text-success" />
            ) : (
              <Copy className="h-3.5 w-3.5" />
            )}
          </button>
        </div>
      )}
      <pre
        className={cn(
          "max-w-full overflow-x-auto whitespace-pre bg-card p-3 font-mono text-xs leading-relaxed text-foreground",
          preClassName,
        )}
      >
        <code>{highlightSql(sql)}</code>
      </pre>
    </div>
  );
}
