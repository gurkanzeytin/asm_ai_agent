import { motion } from "motion/react";
import { MedAgentLogo } from "./MedAgentLogo";
import { TextShimmer } from "./TextShimmer";
import { tr } from "@/locales/tr";
import { COLUMN_QUESTION_STARTERS } from "@/lib/column-question-starters";
import { ArrowUpRight } from "lucide-react";

export function EmptyState({ onPrompt }: { onPrompt?: (prompt: string) => void }) {
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
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.18 }}
        className="mt-9 w-full max-w-3xl"
      >
        <p className="mb-3 text-center text-xs font-medium text-muted-foreground">
          {tr.welcome.questionStarters}
        </p>
        <div className="grid gap-2 sm:grid-cols-2">
          {COLUMN_QUESTION_STARTERS.map((question) => (
            <button
              key={question}
              type="button"
              onClick={() => onPrompt?.(question)}
              className="group flex min-h-14 items-center justify-between gap-3 rounded-xl border border-border/70 bg-background/60 px-4 py-3 text-left text-sm text-foreground shadow-sm backdrop-blur transition hover:-translate-y-0.5 hover:border-primary/50 hover:bg-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
            >
              <span>{question}</span>
              <ArrowUpRight
                aria-hidden="true"
                className="h-4 w-4 shrink-0 text-muted-foreground transition group-hover:text-primary"
              />
            </button>
          ))}
        </div>
      </motion.div>
    </div>
  );
}
