import { motion, useReducedMotion } from "framer-motion";

const LOGO_SRC = "/med-agent-logo.svg?v=3";

export interface MedAgentLogoProps {
  /** Rendered size in px (width = height). Defaults to 180. */
  size?: number;
  className?: string;
  /** Disable only the entrance animation; ambient movement remains available. */
  noIntro?: boolean;
}

export function MedAgentLogo({ size = 180, className, noIntro = false }: MedAgentLogoProps) {
  const reducedMotion = useReducedMotion();
  const animateIntro = !noIntro && !reducedMotion;

  return (
    <motion.div
      style={{ width: size, height: size }}
      initial={animateIntro ? { opacity: 0, scale: 0.9, y: 6 } : false}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      transition={{ duration: animateIntro ? 0.8 : 0, ease: [0.22, 1, 0.36, 1] }}
      whileHover={reducedMotion ? undefined : { scale: 1.04 }}
      className={`relative shrink-0 overflow-hidden ${className ?? ""}`}
    >
      {!reducedMotion && size >= 56 && (
        <motion.span
          aria-hidden="true"
          className="pointer-events-none absolute inset-[8%] -z-10 rounded-full bg-cyan/15 blur-2xl"
          animate={{ opacity: [0.35, 0.7, 0.35], scale: [0.94, 1.06, 0.94] }}
          transition={{ duration: 5.5, repeat: Infinity, ease: "easeInOut" }}
        />
      )}

      <motion.img
        src={LOGO_SRC}
        alt="Med Agent logosu"
        width={size}
        height={size}
        draggable={false}
        className="block h-full w-full select-none object-contain"
        animate={
          reducedMotion
            ? { scale: 0.96 }
            : {
                y: [0, -1.5, 0, 1.5, 0],
                rotate: [0, -0.7, 0, 0.7, 0],
                scale: [0.96, 1, 0.96],
                filter: [
                  "drop-shadow(0 0 0 color-mix(in oklch, var(--cyan) 0%, transparent))",
                  "drop-shadow(0 0 4px color-mix(in oklch, var(--cyan) 28%, transparent))",
                  "drop-shadow(0 0 0 color-mix(in oklch, var(--cyan) 0%, transparent))",
                ],
              }
        }
        transition={{ duration: 5.2, repeat: Infinity, ease: "easeInOut" }}
      />
    </motion.div>
  );
}

export default MedAgentLogo;
