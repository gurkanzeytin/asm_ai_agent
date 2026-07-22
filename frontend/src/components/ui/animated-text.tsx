import { useEffect, useMemo, useRef, useState } from "react";

function splitText(text: string, separator: string) {
  if (!text) return [];
  if (separator === "") return Array.from(text);

  const parts = text.split(separator);
  return parts.flatMap((part, index) => (index === parts.length - 1 ? [part] : [part, separator]));
}

export function useAnimatedText(
  text: string,
  separator = "",
  duration = 0.015,
  enabled = true,
  maxDurationMs = 1200,
) {
  const segments = useMemo(() => splitText(text, separator), [text, separator]);
  const [visibleCount, setVisibleCount] = useState(0);
  const previousTextRef = useRef(text);

  useEffect(() => {
    if (!enabled) {
      setVisibleCount(segments.length);
      previousTextRef.current = text;
      return;
    }

    if (!text) {
      setVisibleCount(0);
      return;
    }

    const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (prefersReducedMotion) {
      setVisibleCount(segments.length);
      return;
    }

    setVisibleCount((count) =>
      text.startsWith(previousTextRef.current) ? Math.min(count, segments.length) : 0,
    );
    previousTextRef.current = text;

    const stepMs = Math.max(duration * 1000, 8);
    const maxTicks = Math.max(1, Math.floor(maxDurationMs / stepMs));
    const increment = Math.max(1, Math.ceil(segments.length / maxTicks));
    const interval = window.setInterval(() => {
      setVisibleCount((count) => {
        if (count >= segments.length) {
          window.clearInterval(interval);
          return count;
        }
        return Math.min(segments.length, count + increment);
      });
    }, stepMs);

    return () => window.clearInterval(interval);
  }, [duration, enabled, maxDurationMs, segments.length, text]);

  return segments.slice(0, visibleCount).join("");
}
