import { motion, AnimatePresence } from "motion/react";
import { Clock, Database, ChevronRight, Copy, Check } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { tr } from "@/locales/tr";
import { panelTransition } from "@/lib/ui-motion";

interface Props {
  open: boolean;
  responseMs: number;
  isThinking: boolean;
  /** Exact SQL generated/executed by the backend for the last request. */
  sql?: string | null;
}

export function InfoPanel({ open, responseMs, isThinking, sql }: Props) {
  const [copied, setCopied] = useState(false);

  const copySql = async () => {
    if (!sql) return;
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error(tr.common.copyFailed);
    }
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.aside
          initial={{ x: 24, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: 16, opacity: 0 }}
          transition={panelTransition}
          className="hidden h-full w-[340px] shrink-0 border-l border-border bg-sidebar/40 lg:block"
        >
          <div className="flex h-16 shrink-0 items-center border-b border-border px-4">
            <div className="text-sm font-semibold">{tr.details.title}</div>
          </div>
          <div className="flex flex-col gap-3 overflow-y-auto p-4">
            <Card title={tr.details.conversation}>
              <Row
                icon={Clock}
                label={tr.details.responseTime}
                value={`${(responseMs / 1000).toFixed(2)}s`}
              />
            </Card>

            <Card title={tr.details.agentStatus}>
              <div className="flex items-center gap-2 text-sm">
                <span
                  className={cn(
                    "h-2 w-2 rounded-full",
                    isThinking ? "bg-warning pulse-ring" : "bg-success",
                  )}
                />
                <span className="text-muted-foreground">
                  {isThinking ? tr.details.thinking : tr.details.idle}
                </span>
              </div>
            </Card>

            <Expandable
              icon={Database}
              title={tr.details.sqlQuery}
              action={
                sql ? (
                  <button
                    type="button"
                    onClick={copySql}
                    title={tr.details.copySql}
                    aria-label={tr.details.copySql}
                    className="grid h-8 w-8 shrink-0 place-items-center rounded-md text-muted-foreground transition hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
                  >
                    {copied ? (
                      <Check className="h-3.5 w-3.5 text-success" />
                    ) : (
                      <Copy className="h-3.5 w-3.5" />
                    )}
                  </button>
                ) : undefined
              }
            >
              {sql ? (
                <pre className="max-h-72 overflow-auto whitespace-pre rounded-lg bg-background/60 p-3 text-[11px] leading-relaxed text-cyan">
                  {sql}
                </pre>
              ) : (
                <p className="rounded-lg bg-background/60 p-3 text-[11px] leading-relaxed text-muted-foreground">
                  {tr.details.noSqlGenerated}
                </p>
              )}
            </Expandable>
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}

function Card({
  title,
  icon: Icon,
  children,
}: {
  title: string;
  icon?: React.ComponentType<{ className?: string }>;
  children: React.ReactNode;
}) {
  return (
    <div className="glass rounded-lg p-4">
      <div className="mb-3 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        {Icon && <Icon className="h-3.5 w-3.5" />}
        {title}
      </div>
      <div className="flex flex-col gap-2">{children}</div>
    </div>
  );
}

function Row({
  icon: Icon,
  label,
  value,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="flex items-center gap-2 text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </span>
      <span className="font-medium">{value}</span>
    </div>
  );
}

function Expandable({
  icon: Icon,
  title,
  children,
  defaultOpen,
  action,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
  action?: React.ReactNode;
}) {
  const [open, setOpen] = useState(!!defaultOpen);
  return (
    <div className="glass rounded-lg">
      <div className="flex items-center pr-2">
        <button
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-center gap-2 px-4 py-3 text-sm font-medium"
        >
          <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
          <span className="flex-1 truncate text-left">{title}</span>
          <ChevronRight
            className={cn("h-4 w-4 shrink-0 text-muted-foreground transition", open && "rotate-90")}
          />
        </button>
        {action}
      </div>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={panelTransition}
            className="overflow-hidden"
          >
            <div className="flex flex-col gap-2 px-4 pb-4">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
