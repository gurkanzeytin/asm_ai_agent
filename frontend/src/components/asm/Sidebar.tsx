import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { Plus, Search, Star, MessageSquare, ChevronLeft, ChevronRight, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Conversation } from "./types";
import { Input } from "@/components/ui/input";
import { MedAgentLogo } from "./MedAgentLogo";
import { tr } from "@/locales/tr";

interface Props {
  conversations: Conversation[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onToggleFavorite: (id: string) => void;
  onDelete: (id: string) => void;
  collapsed: boolean;
  onToggleCollapse: () => void;
}

export function Sidebar({
  conversations,
  activeId,
  onSelect,
  onNew,
  onToggleFavorite,
  onDelete,
  collapsed,
  onToggleCollapse,
}: Props) {
  const [query, setQuery] = useState("");

  const filtered = conversations.filter((c) => c.title.toLowerCase().includes(query.toLowerCase()));
  const favorites = filtered.filter((c) => c.favorite);
  const recents = filtered.filter((c) => !c.favorite);

  return (
    <motion.aside
      animate={{ width: collapsed ? 72 : 288 }}
      transition={{ type: "spring", stiffness: 260, damping: 30 }}
      className="relative z-20 flex h-full flex-col border-r border-border bg-sidebar"
    >
      {/* Header */}
      <div className="flex h-16 shrink-0 items-center gap-3 border-b border-border px-4">
        <div className="shrink-0">
          <MedAgentLogo size={40} noIntro />
        </div>
        <AnimatePresence>
          {!collapsed && (
            <motion.div
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -8 }}
              className="min-w-0 flex-1"
            >
              <div className="truncate text-[15px] font-semibold leading-5 text-foreground">
                Med Agent
              </div>
              <div className="truncate text-xs leading-4 text-muted-foreground">
                {tr.sidebar.appTagline}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* New chat */}
      <div className="px-3">
        <button
          onClick={onNew}
          aria-label={tr.sidebar.newChat}
          title={collapsed ? tr.sidebar.newChat : undefined}
          className={cn(
            "flex w-full items-center gap-2 rounded-xl bg-primary/10 px-3 py-2.5 text-sm font-medium text-primary transition-all hover:bg-primary/20 hover:shadow-[var(--shadow-glow)]",
            collapsed && "justify-center px-0",
          )}
        >
          <Plus className="h-4 w-4 shrink-0" />
          {!collapsed && <span>{tr.sidebar.newChat}</span>}
        </button>
      </div>

      {/* Search */}
      {!collapsed && (
        <div className="mt-3 px-3">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={tr.sidebar.searchConversations}
              className="h-9 rounded-lg border-border bg-background/40 pl-9 text-sm placeholder:text-muted-foreground/70"
            />
          </div>
        </div>
      )}

      {/* Lists */}
      <div className="mt-3 flex-1 overflow-y-auto px-2 pb-2">
        {!collapsed && favorites.length > 0 && (
          <Section title={tr.sidebar.favorites}>
            <AnimatePresence initial={false}>
              {favorites.map((c) => (
                <ConvItem
                  key={c.id}
                  conv={c}
                  active={c.id === activeId}
                  onSelect={onSelect}
                  onFav={onToggleFavorite}
                  onDelete={onDelete}
                />
              ))}
            </AnimatePresence>
          </Section>
        )}
        {!collapsed && (
          <Section title={tr.sidebar.recent}>
            {recents.length === 0 && (
              <div className="px-3 py-2 text-xs text-muted-foreground">
                {tr.sidebar.noConversations}
              </div>
            )}
            <AnimatePresence initial={false}>
              {recents.map((c) => (
                <ConvItem
                  key={c.id}
                  conv={c}
                  active={c.id === activeId}
                  onSelect={onSelect}
                  onFav={onToggleFavorite}
                  onDelete={onDelete}
                />
              ))}
            </AnimatePresence>
          </Section>
        )}
        {collapsed &&
          conversations.slice(0, 8).map((c) => (
            <button
              key={c.id}
              onClick={() => onSelect(c.id)}
              className={cn(
                "mx-auto my-1 grid h-9 w-9 place-items-center rounded-lg text-muted-foreground transition hover:bg-accent hover:text-foreground",
                c.id === activeId && "bg-primary/15 text-primary",
              )}
              title={c.title}
            >
              <MessageSquare className="h-4 w-4" />
            </button>
          ))}
      </div>

      {/* Collapse toggle */}
      <button
        onClick={onToggleCollapse}
        className="absolute -right-3 top-5 z-30 grid h-6 w-6 place-items-center rounded-full border border-border bg-card text-muted-foreground shadow-md transition hover:text-foreground"
        aria-label={tr.sidebar.toggleSidebar}
        aria-expanded={!collapsed}
      >
        {collapsed ? <ChevronRight className="h-3 w-3" /> : <ChevronLeft className="h-3 w-3" />}
      </button>
    </motion.aside>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-2">
      <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/80">
        {title}
      </div>
      <div className="flex flex-col gap-0.5">{children}</div>
    </div>
  );
}

function ConvItem({
  conv,
  active,
  onSelect,
  onFav,
  onDelete,
}: {
  conv: Conversation;
  active: boolean;
  onSelect: (id: string) => void;
  onFav: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  return (
    <motion.div
      layout
      initial={{ opacity: 0, x: -12, scale: 0.98 }}
      animate={{ opacity: 1, x: 0, scale: 1 }}
      exit={{ opacity: 0, x: -8, scale: 0.98 }}
      transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
      className={cn(
        "group relative flex items-center rounded-lg text-sm transition",
        active
          ? "bg-primary/15 text-foreground"
          : "text-muted-foreground hover:bg-accent hover:text-foreground",
      )}
    >
      {active && (
        <span className="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-r bg-primary" />
      )}
      <button
        type="button"
        onClick={() => onSelect(conv.id)}
        aria-current={active ? "page" : undefined}
        className="flex min-w-0 flex-1 items-center gap-2 rounded-l-lg px-3 py-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary"
      >
        <MessageSquare className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        <span className="truncate flex-1">{conv.title}</span>
      </button>
      <div className="flex shrink-0 items-center gap-0.5 pr-1">
        <button
          type="button"
          onClick={() => onFav(conv.id)}
          aria-label={tr.sidebar.favoriteConversation}
          title={tr.sidebar.favoriteConversation}
          className="grid h-6 w-6 place-items-center rounded hover:bg-background/40"
        >
          <Star
            className={cn(
              "h-3 w-3",
              conv.favorite ? "fill-warning text-warning" : "text-muted-foreground",
            )}
          />
        </button>
        <button
          type="button"
          onClick={() => onDelete(conv.id)}
          aria-label={tr.sidebar.deleteConversation}
          title={tr.sidebar.deleteConversation}
          className="grid h-6 w-6 place-items-center rounded text-muted-foreground hover:bg-background/40 hover:text-destructive"
        >
          <Trash2 className="h-3 w-3" />
        </button>
      </div>
    </motion.div>
  );
}
