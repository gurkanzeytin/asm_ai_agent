import { motion } from "motion/react";
import { Activity, Building2, Stethoscope, FileBarChart } from "lucide-react";
import { MedAgentLogo } from "./MedAgentLogo";

const suggestions = [
  {
    icon: Activity,
    title: "Today's patient statistics",
    prompt: "Show today's patient statistics across all family health centers.",
  },
  {
    icon: Building2,
    title: "Center performance",
    prompt: "Analyze family health center performance for the last 30 days.",
  },
  {
    icon: Stethoscope,
    title: "Busiest doctor",
    prompt: "Find the busiest doctor this week and their patient load.",
  },
  {
    icon: FileBarChart,
    title: "Monthly report",
    prompt: "Generate a monthly performance report with key KPIs.",
  },
];

export function EmptyState({ onPick }: { onPick: (prompt: string) => void }) {
  return (
    <div className="flex min-h-full flex-col items-center justify-center px-4 py-16">
      <motion.div
        initial={{ opacity: 0, scale: 0.9 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.4 }}
        className="mb-6"
      >
        <MedAgentLogo size={80} noIntro />
      </motion.div>
      <motion.h1
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="text-center text-3xl font-semibold tracking-tight sm:text-4xl"
      >
        How can I help you <span className="gradient-text">today</span>?
      </motion.h1>
      <motion.p
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.15 }}
        className="mt-3 max-w-lg text-center text-sm text-muted-foreground"
      >
        Ask questions about your organization, run SQL against the knowledge base, analyze
        documents or generate reports — all in natural language.
      </motion.p>

      <div className="mt-10 grid w-full max-w-2xl grid-cols-1 gap-3 sm:grid-cols-2">
        {suggestions.map((s, i) => (
          <motion.button
            key={s.title}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 + i * 0.05 }}
            whileHover={{ y: -2 }}
            onClick={() => onPick(s.prompt)}
            className="glass group flex items-start gap-3 rounded-2xl p-4 text-left transition hover:border-primary/40"
          >
            <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary transition group-hover:bg-primary/20">
              <s.icon className="h-4 w-4" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium">{s.title}</div>
              <div className="mt-0.5 truncate text-xs text-muted-foreground">{s.prompt}</div>
            </div>
          </motion.button>
        ))}
      </div>
    </div>
  );
}
