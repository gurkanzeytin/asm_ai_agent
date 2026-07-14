import { useId, useRef, useState } from "react";
import {
  motion,
  useAnimationFrame,
  useMotionValue,
  useReducedMotion,
  useTransform,
} from "framer-motion";

const BLUE = "#2563EB";
const CYAN = "#06B6D4";

/** Circuit node positions (centers) inside the "M" */
const NODES: Array<[number, number]> = [
  [72, 92],
  [128, 92],
  [100, 126],
  [72, 140],
  [128, 140],
];

/** Rounded hexagon speech-bubble outline with a soft tail */
const HEX_PATH =
  "M 92 21.5 Q 100 17 108 21.5 L 159.5 51.5 Q 167.5 56 167.5 65 " +
  "L 167.5 125 Q 167.5 134 159.5 138.5 L 113 165.4 " +
  "C 107 168.9 104.5 173.5 104 179.5 C 103.6 184.7 98.6 186.6 95.2 183.2 " +
  "C 92.4 180.4 89 172.6 80.5 167.7 L 40.5 138.5 Q 32.5 134 32.5 125 " +
  "L 32.5 65 Q 32.5 56 40.5 51.5 Z";

/** Letter M strokes + stethoscope stem */
const M_PATH = "M 72 140 L 72 92 L 100 126 L 128 92 L 128 140 M 100 126 L 100 148";

export interface MedAgentLogoProps {
  /** Rendered size in px (width = height). Defaults to 180. */
  size?: number;
  className?: string;
  /** Disable the intro (fade/scale/sequential) animation. */
  noIntro?: boolean;
}

export function MedAgentLogo({ size = 180, className, noIntro = false }: MedAgentLogoProps) {
  const uid = useId().replace(/:/g, "");
  const gradId = `ma-grad-${uid}`;
  const glowId = `ma-glow-${uid}`;
  const reduced = useReducedMotion();
  const [hovered, setHovered] = useState(false);

  // Gradient flow — manual offset so hover can smoothly change speed.
  // Continuous modulo loop with symmetric BLUE→CYAN→BLUE stops = no visible seam.
  const offset = useMotionValue(0);
  const speed = useRef(1 / 9); // cycles per second (idle ~9s, calmer)
  speed.current = hovered ? 1 / 4.5 : 1 / 9;
  useAnimationFrame((_, delta) => {
    if (reduced) return;
    offset.set((offset.get() + (delta / 1000) * speed.current) % 1);
  });
  const x1 = useTransform(offset, (v) => v - 1);
  const x2 = useTransform(offset, (v) => v);

  const introDur = noIntro || reduced ? 0 : 1.4;
  const idleDelay = noIntro || reduced ? 0 : 1.7;

  return (
    <motion.div
      className={className}
      style={{
        width: size,
        height: size,
        cursor: "pointer",
        willChange: "transform",
        position: "relative",
      }}
      initial={noIntro || reduced ? false : { opacity: 0, scale: 0.92 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: introDur, ease: [0.22, 1, 0.36, 1] }}
      whileHover={reduced ? undefined : { scale: 1.05 }}
      onHoverStart={() => setHovered(true)}
      onHoverEnd={() => setHovered(false)}
      aria-label="MedAgent logo"
      role="img"
    >
      {/* Ambient breathing glow behind the icon */}
      {!reduced && (
        <motion.div
          aria-hidden
          style={{
            position: "absolute",
            inset: "-30%",
            borderRadius: "9999px",
            background:
              "radial-gradient(circle, rgba(37,99,235,0.28) 0%, rgba(6,182,212,0.10) 45%, transparent 72%)",
            filter: "blur(28px)",
            zIndex: -1,
            willChange: "opacity, transform",
          }}
          animate={{ opacity: [0.55, 0.9, 0.55], scale: [0.96, 1.04, 0.96] }}
          transition={{
            duration: 8,
            repeat: Infinity,
            ease: "easeInOut",
            delay: idleDelay,
          }}
        />
      )}

      {/* Floating vertical drift (1.5px) — synced to breathing */}
      <motion.div
        style={{ width: "100%", height: "100%", willChange: "transform" }}
        animate={reduced ? undefined : { y: [0, -1.5, 0, 1.5, 0] }}
        transition={
          reduced
            ? undefined
            : { duration: 8, repeat: Infinity, ease: "easeInOut", delay: idleDelay }
        }
      >
        <motion.svg
          viewBox="0 0 200 200"
          width="100%"
          height="100%"
          fill="none"
          style={{ display: "block", willChange: "transform" }}
          animate={reduced ? undefined : { scale: [1, 1.025, 1] }}
          transition={
            reduced
              ? undefined
              : { duration: 8, repeat: Infinity, ease: "easeInOut", delay: idleDelay }
          }
        >
          <defs>
            <motion.linearGradient
              id={gradId}
              gradientUnits="objectBoundingBox"
              spreadMethod="repeat"
              x1={reduced ? 0 : x1}
              y1={0}
              x2={reduced ? 1 : x2}
              y2={0.55}
            >
              <stop offset="0" stopColor={BLUE} />
              <stop offset="0.5" stopColor={CYAN} />
              <stop offset="1" stopColor={BLUE} />
            </motion.linearGradient>
            <filter id={glowId} x="-80%" y="-80%" width="260%" height="260%">
              <feGaussianBlur stdDeviation="5.5" />
            </filter>
          </defs>

          {/* Hexagon speech bubble */}
          <g id="hexagon">
            <path
              d={HEX_PATH}
              stroke={`url(#${gradId})`}
              strokeWidth={9}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
          </g>

          {/* Medical cross — heartbeat every ~3.6s (calmer) */}
          <motion.g
            id="medical-cross"
            style={{ transformBox: "fill-box", transformOrigin: "center", willChange: "transform" }}
            animate={
              reduced
                ? undefined
                : {
                    scale: [1, 1.07, 1, 1],
                    filter: [
                      "drop-shadow(0 0 0px rgba(6,182,212,0))",
                      "drop-shadow(0 0 9px rgba(6,182,212,0.5))",
                      "drop-shadow(0 0 0px rgba(6,182,212,0))",
                      "drop-shadow(0 0 0px rgba(6,182,212,0))",
                    ],
                  }
            }
            transition={
              reduced
                ? undefined
                : {
                    duration: 3.6,
                    times: [0, 0.14, 0.34, 1],
                    ease: "easeInOut",
                    repeat: Infinity,
                    delay: idleDelay * 0.7,
                  }
            }
          >
            <rect x={95} y={36} width={10} height={28} rx={2.5} fill={`url(#${gradId})`} />
            <rect x={86} y={45} width={28} height={10} rx={2.5} fill={`url(#${gradId})`} />
          </motion.g>

          {/* Letter M */}
          <g id="letter-m">
            <path
              d={M_PATH}
              stroke={`url(#${gradId})`}
              strokeWidth={7}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </g>

          {/* Circuit nodes — sequential soft illumination (organic, gentle) */}
          <g id="circuit-nodes">
            {NODES.map(([cx, cy], i) => (
              <g key={i}>
                {/* soft glow — dimmer, longer, more organic */}
                <motion.circle
                  cx={cx}
                  cy={cy}
                  r={9}
                  fill={CYAN}
                  filter={`url(#${glowId})`}
                  initial={{ opacity: 0 }}
                  animate={reduced ? { opacity: 0 } : { opacity: [0, 0.42, 0.28, 0] }}
                  transition={
                    reduced
                      ? undefined
                      : {
                          duration: 2.6,
                          times: [0, 0.35, 0.6, 1],
                          repeat: Infinity,
                          ease: "easeInOut",
                          delay: (noIntro ? 0 : 0.6) + i * 0.44,
                          repeatDelay: 0.9,
                        }
                  }
                />
                {/* donut node */}
                <motion.circle
                  cx={cx}
                  cy={cy}
                  r={7.5}
                  stroke={`url(#${gradId})`}
                  strokeWidth={5}
                  fill="var(--background)"
                  initial={noIntro || reduced ? false : { opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ duration: 0.5, delay: noIntro || reduced ? 0 : 0.4 + i * 0.14 }}
                />
              </g>
            ))}
          </g>
        </motion.svg>
      </motion.div>
    </motion.div>
  );
}

export default MedAgentLogo;
