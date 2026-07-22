import { motion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

interface Segment {
  key: number;
  text: string;
}

/**
 * Renders growing plain text with each newly-arrived chunk fading/blurring in,
 * plus a blinking cursor while `streaming` is true — an AI-typewriter effect.
 * Already-rendered segments never re-animate, only the delta does.
 */
export function StreamingText({
  text,
  streaming,
  className,
}: {
  text: string;
  streaming: boolean;
  className?: string;
}) {
  const [segments, setSegments] = useState<Segment[]>([]);
  const prevLengthRef = useRef(0);
  const nextKeyRef = useRef(0);

  useEffect(() => {
    if (text.length < prevLengthRef.current) {
      nextKeyRef.current = 0;
      prevLengthRef.current = text.length;
      setSegments(text ? [{ key: nextKeyRef.current++, text }] : []);
      return;
    }
    const delta = text.slice(prevLengthRef.current);
    if (!delta) return;
    prevLengthRef.current = text.length;
    setSegments((prev) => [...prev, { key: nextKeyRef.current++, text: delta }]);
  }, [text]);

  return (
    <span className={cn("whitespace-pre-wrap", className)}>
      {segments.map((segment) => (
        <motion.span
          key={segment.key}
          initial={{ opacity: 0, filter: "blur(4px)" }}
          animate={{ opacity: 1, filter: "blur(0px)" }}
          transition={{ duration: 0.35, ease: "easeOut" }}
        >
          {segment.text}
        </motion.span>
      ))}
      {streaming && (
        <motion.span
          aria-hidden="true"
          className="ml-0.5 inline-block h-[1em] w-[2px] translate-y-[2px] bg-current align-middle"
          animate={{ opacity: [1, 1, 0, 0] }}
          transition={{ duration: 1, repeat: Infinity, ease: "linear", times: [0, 0.5, 0.5, 1] }}
        />
      )}
    </span>
  );
}
