import { motion } from "motion/react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { User, Copy, Check } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";
import type { Message } from "./types";
import { SqlResultsTable } from "./SqlResultsTable";
import { tr } from "@/locales/tr";
import { MedAgentLogo } from "./MedAgentLogo";

export function ChatMessage({ message }: { message: Message }) {
  const isUser = message.role === "user";
  const [copied, setCopied] = useState(false);

  const copy = () => {
    navigator.clipboard.writeText(message.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className={cn("group flex gap-3", isUser && "flex-row-reverse")}
    >
      <div
        className={cn(
          "grid h-8 w-8 shrink-0 place-items-center",
          isUser
            ? "rounded-lg bg-primary/20 text-primary"
            : "rounded-full border border-cyan/25 bg-primary/10 shadow-[0_0_18px_rgba(14,165,233,0.12)]",
        )}
      >
        {isUser ? (
          <User className="h-4 w-4" />
        ) : (
          <span aria-hidden="true">
            <MedAgentLogo size={23} noIntro className="[&_svg]:!block" />
          </span>
        )}
      </div>

      <div
        className={cn(
          "flex min-w-0 flex-col gap-1.5",
          message.sqlResult ? "max-w-full flex-1" : "max-w-[80%]",
          isUser && "items-end",
        )}
      >
        <div
          className={cn(
            "rounded-2xl px-4 py-3 text-sm leading-relaxed",
            isUser
              ? "bg-primary text-primary-foreground rounded-tr-sm"
              : "glass rounded-tl-sm text-foreground",
          )}
        >
          {isUser ? (
            <p className="whitespace-pre-wrap">{message.content}</p>
          ) : (
            <div className="prose-chat">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  code({ className, children, ...props }) {
                    const isBlock = className?.includes("language-");
                    if (isBlock) {
                      return (
                        <pre className="my-2 overflow-x-auto rounded-lg border border-border bg-background/60 p-3 text-xs">
                          <code {...props}>{children}</code>
                        </pre>
                      );
                    }
                    return (
                      <code
                        className="rounded bg-background/60 px-1.5 py-0.5 text-xs text-cyan"
                        {...props}
                      >
                        {children}
                      </code>
                    );
                  },
                  table({ children }) {
                    return (
                      <div className="my-2 overflow-x-auto rounded-lg border border-border">
                        <table className="w-full text-xs">{children}</table>
                      </div>
                    );
                  },
                  th({ children }) {
                    return (
                      <th className="border-b border-border bg-background/40 px-3 py-2 text-left font-medium">
                        {children}
                      </th>
                    );
                  },
                  td({ children }) {
                    return <td className="border-b border-border/50 px-3 py-2">{children}</td>;
                  },
                  a({ children, href }) {
                    return (
                      <a href={href} className="text-primary underline-offset-2 hover:underline">
                        {children}
                      </a>
                    );
                  },
                  ul({ children }) {
                    return <ul className="my-2 list-disc space-y-1 pl-5">{children}</ul>;
                  },
                  ol({ children }) {
                    return <ol className="my-2 list-decimal space-y-1 pl-5">{children}</ol>;
                  },
                  p({ children }) {
                    return <p className="my-1.5 first:mt-0 last:mb-0">{children}</p>;
                  },
                  h1: ({ children }) => <h1 className="mt-3 text-lg font-semibold">{children}</h1>,
                  h2: ({ children }) => (
                    <h2 className="mt-3 text-base font-semibold">{children}</h2>
                  ),
                  h3: ({ children }) => <h3 className="mt-2 text-sm font-semibold">{children}</h3>,
                }}
              >
                {message.content}
              </ReactMarkdown>
            </div>
          )}
        </div>
        {!isUser && message.sqlResult && !message.streaming && (
          <div className="w-full">
            <SqlResultsTable data={message.sqlResult} />
          </div>
        )}
        {!isUser && !message.streaming && (
          <div className="flex items-center gap-1 opacity-0 transition group-hover:opacity-100">
            <button
              onClick={copy}
              className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
              {copied ? tr.common.copied : tr.common.copy}
            </button>
          </div>
        )}
      </div>
    </motion.div>
  );
}

export function TypingIndicator() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex gap-3"
    >
      <div className="grid h-8 w-8 shrink-0 place-items-center rounded-full border border-cyan/25 bg-primary/10 shadow-[0_0_18px_rgba(14,165,233,0.12)]">
        <span aria-hidden="true">
          <MedAgentLogo size={23} noIntro className="[&_svg]:!block" />
        </span>
      </div>
      <div className="glass flex items-center gap-1.5 rounded-2xl rounded-tl-sm px-4 py-3.5">
        <span className="typing-dot h-1.5 w-1.5 rounded-full bg-primary" />
        <span className="typing-dot h-1.5 w-1.5 rounded-full bg-primary" />
        <span className="typing-dot h-1.5 w-1.5 rounded-full bg-primary" />
        <span className="ml-2 text-xs text-muted-foreground">{tr.chat.thinking}</span>
      </div>
    </motion.div>
  );
}
