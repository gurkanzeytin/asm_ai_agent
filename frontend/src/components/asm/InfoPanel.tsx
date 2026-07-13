import { motion, AnimatePresence } from "motion/react";
import {
  Zap,
  Clock,
  Cpu,
  FileText,
  Database,
  Wrench,
  Brain,
  ChevronRight,
  X,
} from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";

interface Props {
  open: boolean;
  onClose: () => void;
  tokens: number;
  responseMs: number;
  model: string;
  isThinking: boolean;
}

export function InfoPanel({ open, onClose, tokens, responseMs, model, isThinking }: Props) {
  return (
    <AnimatePresence>
      {open && (
        <motion.aside
          initial={{ x: 340, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: 340, opacity: 0 }}
          transition={{ type: "spring", stiffness: 260, damping: 30 }}
          className="hidden h-full w-[340px] shrink-0 border-l border-border bg-sidebar/40 lg:block"
        >
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <div className="text-sm font-semibold">Details</div>
            <button
              onClick={onClose}
              className="grid h-7 w-7 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="flex flex-col gap-3 overflow-y-auto p-4">
            <Card title="Conversation">
              <Row icon={Cpu} label="Model" value={model} />
              <Row icon={Zap} label="Tokens used" value={tokens.toLocaleString()} />
              <Row icon={Clock} label="Response time" value={`${(responseMs / 1000).toFixed(2)}s`} />
            </Card>

            <Card title="Agent status">
              <div className="flex items-center gap-2 text-sm">
                <span
                  className={cn(
                    "h-2 w-2 rounded-full",
                    isThinking ? "bg-warning pulse-ring" : "bg-success"
                  )}
                />
                <span className="text-muted-foreground">
                  {isThinking ? "Reasoning through query…" : "Idle — ready for next task"}
                </span>
              </div>
            </Card>

            <Expandable
              icon={FileText}
              title="Retrieved documents"
              badge="3"
              defaultOpen
            >
              <DocRow name="Q3-financial-report.pdf" score={0.94} />
              <DocRow name="Patient-flow-guidelines.md" score={0.88} />
              <DocRow name="Center-performance-2024.xlsx" score={0.81} />
            </Expandable>

            <Expandable icon={Database} title="SQL query">
              <pre className="overflow-x-auto rounded-lg bg-background/60 p-3 text-[11px] leading-relaxed text-cyan">
{`SELECT c.name, COUNT(v.id) AS visits
FROM centers c
LEFT JOIN visits v
  ON v.center_id = c.id
 AND v.date = CURRENT_DATE
GROUP BY c.name
ORDER BY visits DESC;`}
              </pre>
            </Expandable>

            <Expandable icon={Wrench} title="Tool calls" badge="2">
              <ToolRow name="query_database" status="success" ms={412} />
              <ToolRow name="format_table" status="success" ms={38} />
            </Expandable>

            <Card title="Reasoning" icon={Brain}>
              <p className="text-xs leading-relaxed text-muted-foreground">
                Interpreted request, selected knowledge sources, generated SQL, validated results,
                composed final answer.
              </p>
            </Card>
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
    <div className="glass rounded-2xl p-4">
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
  badge,
  children,
  defaultOpen,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  badge?: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(!!defaultOpen);
  return (
    <div className="glass rounded-2xl">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-4 py-3 text-sm font-medium"
      >
        <Icon className="h-4 w-4 text-muted-foreground" />
        <span className="flex-1 text-left">{title}</span>
        {badge && (
          <span className="rounded-full bg-primary/15 px-2 py-0.5 text-[10px] font-semibold text-primary">
            {badge}
          </span>
        )}
        <ChevronRight
          className={cn("h-4 w-4 text-muted-foreground transition", open && "rotate-90")}
        />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="flex flex-col gap-2 px-4 pb-4">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function DocRow({ name, score }: { name: string; score: number }) {
  return (
    <div className="flex items-center gap-2 rounded-lg bg-background/40 px-3 py-2 text-xs">
      <FileText className="h-3.5 w-3.5 shrink-0 text-primary" />
      <span className="min-w-0 flex-1 truncate">{name}</span>
      <span className="shrink-0 text-muted-foreground">{score.toFixed(2)}</span>
    </div>
  );
}

function ToolRow({
  name,
  status,
  ms,
}: {
  name: string;
  status: "success" | "error";
  ms: number;
}) {
  return (
    <div className="flex items-center gap-2 rounded-lg bg-background/40 px-3 py-2 text-xs">
      <span
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          status === "success" ? "bg-success" : "bg-destructive"
        )}
      />
      <span className="flex-1 font-mono text-[11px]">{name}</span>
      <span className="text-muted-foreground">{ms}ms</span>
    </div>
  );
}
