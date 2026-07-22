import { motion } from "motion/react";
import { Activity, Building2, Stethoscope, FileBarChart } from "lucide-react";
import { MedAgentLogo } from "./MedAgentLogo";
import { TextShimmer } from "./TextShimmer";
import { tr } from "@/locales/tr";

const suggestions = [
  {
    icon: Activity,
    title: tr.suggestions.patientStatistics.title,
    prompt: tr.suggestions.patientStatistics.description,
  },
  {
    icon: Building2,
    title: tr.suggestions.centerPerformance.title,
    prompt: tr.suggestions.centerPerformance.description,
  },
  {
    icon: Stethoscope,
    title: tr.suggestions.busiestDoctor.title,
    prompt: tr.suggestions.busiestDoctor.description,
  },
  {
    icon: FileBarChart,
    title: tr.suggestions.monthlyReport.title,
    prompt: tr.suggestions.monthlyReport.description,
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
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
      >
        <TextShimmer
          as="h1"
          duration={2.5}
          className="py-1 text-center text-3xl font-semibold leading-[1.3] tracking-tight sm:text-4xl"
        >
          {`${tr.welcome.titleBefore} ${tr.welcome.titleHighlight}?`}
        </TextShimmer>
      </motion.div>

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
