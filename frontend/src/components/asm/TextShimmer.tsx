import { motion } from "motion/react";
import { useMemo, type ElementType, type CSSProperties } from "react";
import { cn } from "@/lib/utils";

interface TextShimmerProps {
  children: string;
  as?: ElementType;
  className?: string;
  duration?: number;
  spread?: number;
}

/** Animated gradient sweep across text via background-position, clipped to the glyphs. */
export function TextShimmer({
  children,
  as: Component = "span",
  className,
  duration = 2,
  spread = 2,
}: TextShimmerProps) {
  const MotionComponent = useMemo(() => motion.create(Component), [Component]);
  const dynamicSpread = children.length * spread;

  return (
    <MotionComponent
      className={cn(
        "relative inline-block bg-[length:250%_100%,auto] bg-clip-text text-transparent [background-repeat:no-repeat,padding-box]",
        "[--base-color:var(--primary)] [--base-gradient-color:var(--cyan)]",
        "[--bg:linear-gradient(90deg,#0000_calc(50%-var(--spread)),var(--base-gradient-color),#0000_calc(50%+var(--spread)))]",
        "[background-image:var(--bg),linear-gradient(var(--base-color),var(--base-color))]",
        className,
      )}
      initial={{ backgroundPosition: "100% center" }}
      animate={{ backgroundPosition: "0% center" }}
      transition={{ repeat: Infinity, duration, ease: "linear" }}
      style={{ "--spread": `${dynamicSpread}px` } as CSSProperties}
    >
      {children}
    </MotionComponent>
  );
}
