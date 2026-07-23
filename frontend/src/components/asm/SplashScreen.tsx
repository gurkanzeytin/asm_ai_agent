import { motion, AnimatePresence } from "motion/react";
import { MedAgentLogo } from "./MedAgentLogo";
import { tr } from "@/locales/tr";

interface Props {
  visible: boolean;
  onReady: () => void;
  onFinish?: () => void;
}

export function SplashScreen({ visible, onReady, onFinish }: Props) {
  return (
    <AnimatePresence onExitComplete={onFinish}>
      {visible && (
        <motion.div
          initial={{ opacity: 1 }}
          exit={{ opacity: 0, scale: 1.015 }}
          transition={{ duration: 0.65, ease: [0.22, 1, 0.36, 1] }}
          className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-background"
        >
          <MedAgentLogo size={120} />
          <motion.p
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.6, duration: 0.5 }}
            className="mt-6 text-sm font-medium text-muted-foreground/80"
          >
            {tr.splash.loading}
          </motion.p>
          <motion.div
            initial={{ scaleX: 0 }}
            animate={{ scaleX: [0, 0.86, 1] }}
            transition={{ delay: 0.35, duration: 1.45, times: [0, 0.78, 1], ease: "easeInOut" }}
            onAnimationComplete={onReady}
            className="mt-6 h-0.5 w-32 origin-left overflow-hidden rounded-full bg-gradient-to-r from-primary to-cyan shadow-[0_0_14px_color-mix(in_oklch,var(--cyan)_28%,transparent)]"
          />
        </motion.div>
      )}
    </AnimatePresence>
  );
}
