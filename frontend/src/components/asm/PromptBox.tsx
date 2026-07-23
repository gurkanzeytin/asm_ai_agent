import { useEffect, useRef } from "react";
import { motion } from "motion/react";
import { Send, Square } from "lucide-react";
import { cn } from "@/lib/utils";
import { tr } from "@/locales/tr";

interface Props {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  onStop: () => void;
  isGenerating: boolean;
}

export function PromptBox({ value, onChange, onSend, onStop, isGenerating }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const previousValueRef = useRef(value);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
    if (!previousValueRef.current && value) el.focus();
    previousValueRef.current = value;
  }, [value]);

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!isGenerating && value.trim()) onSend();
    }
  };

  return (
    <div className="mx-auto w-full max-w-3xl px-4 pb-6">
      <div className="glass group relative rounded-2xl border border-border/80 p-2 shadow-[var(--shadow-panel)] transition focus-within:border-primary/40 focus-within:shadow-[var(--shadow-glow)]">
        <textarea
          ref={ref}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
          rows={1}
          placeholder={tr.chat.placeholder}
          className="min-h-11 max-h-[200px] w-full resize-none bg-transparent px-3 py-3 pr-14 text-sm leading-5 text-foreground placeholder:text-muted-foreground/70 focus:outline-none"
        />
        {isGenerating ? (
          <motion.button
            type="button"
            onClick={onStop}
            whileHover={{ scale: 1.04 }}
            whileTap={{ scale: 0.94 }}
            aria-label={tr.common.stop}
            className="absolute bottom-2.5 right-2.5 grid h-10 w-10 place-items-center rounded-lg bg-destructive/90 text-destructive-foreground shadow-lg transition-colors hover:bg-destructive focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-destructive/60"
          >
            <Square className="h-3.5 w-3.5 fill-current" />
          </motion.button>
        ) : (
          <motion.button
            type="button"
            onClick={onSend}
            disabled={!value.trim()}
            whileHover={value.trim() ? { scale: 1.05, y: -1 } : undefined}
            whileTap={value.trim() ? { scale: 0.92 } : undefined}
            className={cn(
              "absolute bottom-2.5 right-2.5 grid h-10 w-10 place-items-center rounded-lg transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60",
              value.trim()
                ? "bg-gradient-to-br from-primary to-cyan text-primary-foreground shadow-[0_8px_20px_-8px_color-mix(in_oklch,var(--cyan)_55%,transparent)]"
                : "bg-muted text-muted-foreground",
            )}
            aria-label={tr.chat.sendLabel}
          >
            <motion.span
              animate={value.trim() ? { x: [0, 1, 0], y: [0, -1, 0] } : { x: 0, y: 0 }}
              transition={{ duration: 1.8, repeat: value.trim() ? Infinity : 0, repeatDelay: 1.2 }}
            >
              <Send className="h-4 w-4" />
            </motion.span>
          </motion.button>
        )}
      </div>
    </div>
  );
}
