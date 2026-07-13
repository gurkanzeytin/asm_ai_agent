import { useEffect, useRef } from "react";
import { Send, Paperclip, Mic, X, Square } from "lucide-react";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

interface Props {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  onStop: () => void;
  isGenerating: boolean;
}

export function PromptBox({ value, onChange, onSend, onStop, isGenerating }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  }, [value]);

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!isGenerating && value.trim()) onSend();
    }
  };

  return (
    <div className="mx-auto w-full max-w-3xl px-4 pb-6">
      <div className="glass group relative rounded-3xl border border-border/80 p-2 shadow-[var(--shadow-panel)] transition focus-within:border-primary/40 focus-within:shadow-[var(--shadow-glow)]">
        <textarea
          ref={ref}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
          rows={1}
          placeholder="Ask anything..."
          className="max-h-[200px] w-full resize-none bg-transparent px-3 py-2.5 text-sm text-foreground placeholder:text-muted-foreground/70 focus:outline-none"
        />
        <div className="flex items-center justify-between gap-2 px-1">
          <div className="flex items-center gap-1">
            <IconBtn
              title="Upload file"
              onClick={() => toast.info("File upload", { description: "Attach documents, images or PDFs." })}
            >
              <Paperclip className="h-4 w-4" />
            </IconBtn>
            <IconBtn
              title="Voice input"
              onClick={() => toast.info("Voice input", { description: "Recording will start when microphone is enabled." })}
            >
              <Mic className="h-4 w-4" />
            </IconBtn>
            {value && (
              <IconBtn title="Clear" onClick={() => onChange("")}>
                <X className="h-4 w-4" />
              </IconBtn>
            )}
          </div>
          <div className="flex items-center gap-2">
            <span className="hidden text-[11px] text-muted-foreground sm:block">
              <kbd className="rounded border border-border bg-background/40 px-1.5 py-0.5 text-[10px]">
                ↵
              </kbd>{" "}
              send ·{" "}
              <kbd className="rounded border border-border bg-background/40 px-1.5 py-0.5 text-[10px]">
                ⇧↵
              </kbd>{" "}
              new line
            </span>
            {isGenerating ? (
              <button
                onClick={onStop}
                className="flex h-9 items-center gap-1.5 rounded-xl bg-destructive/90 px-3 text-xs font-medium text-destructive-foreground transition hover:bg-destructive"
              >
                <Square className="h-3 w-3 fill-current" />
                Stop
              </button>
            ) : (
              <button
                onClick={onSend}
                disabled={!value.trim()}
                className={cn(
                  "grid h-9 w-9 place-items-center rounded-xl transition",
                  value.trim()
                    ? "bg-gradient-to-br from-primary to-cyan text-primary-foreground shadow-[var(--shadow-glow)] hover:opacity-90"
                    : "bg-muted text-muted-foreground"
                )}
                aria-label="Send"
              >
                <Send className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>
      </div>
      <p className="mt-2 text-center text-[11px] text-muted-foreground/70">
        ASM AI can make mistakes. Verify important healthcare information.
      </p>
    </div>
  );
}

function IconBtn({
  children,
  title,
  onClick,
}: {
  children: React.ReactNode;
  title: string;
  onClick?: () => void;
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      className="grid h-9 w-9 place-items-center rounded-lg text-muted-foreground transition hover:bg-accent hover:text-foreground"
    >
      {children}
    </button>
  );
}
