import { motion } from "motion/react";
import { MedAgentLogo } from "./MedAgentLogo";
import { TextShimmer } from "./TextShimmer";
import { tr } from "@/locales/tr";

export function EmptyState() {
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
    </div>
  );
}
