import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import {
  Plus,
  Search,
  Star,
  MessageSquare,
  Settings,
  ChevronLeft,
  ChevronRight,
  Trash2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { Conversation } from "./types";
import { Input } from "@/components/ui/input";
import { MedAgentLogo } from "./MedAgentLogo";

interface Props {
  conversations: Conversation[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onToggleFavorite: (id: string) => void;
  onDelete: (id: string) => void;
  onOpenSettings: () => void;
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
  onOpenSettings,
  collapsed,
  onToggleCollapse,
}: Props) {
  const [query, setQuery] = useState("");

  const filtered = conversations.filter((c) =>
    c.title.toLowerCase().includes(query.toLowerCase())
  );
  const favorites = filtered.filter((c) => c.favorite);
  const recents = filtered.filter((c) => !c.favorite);

  return (
    <motion.aside
      animate={{ width: collapsed ? 72 : 288 }}
      transition={{ type: "spring", stiffness: 260, damping: 30 }}
      className="relative z-20 flex h-full flex-col border-r border-border bg-sidebar"
    >
      {/* Header */}
      <div className="flex items-center gap-3 p-4">
        <div className="shrink-0">
          <MedAgentLogo size={36} noIntro className="[&_svg]:!block" />
        </div>
        <AnimatePresence>
          {!collapsed && (
            <motion.div
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -8 }}
              className="min-w-0 flex-1"
            >
              <div className="truncate text-sm font-semibold">ASM AI Agent</div>
              <div className="truncate text-[11px] text-muted-foreground">
                Healthcare Intelligence
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* New chat */}
      <div className="px-3">
        <button
          onClick={onNew}
          className={cn(
            "flex w-full items-center gap-2 rounded-xl bg-primary/10 px-3 py-2.5 text-sm font-medium text-primary transition-all hover:bg-primary/20 hover:shadow-[var(--shadow-glow)]",
            collapsed && "justify-center px-0"
          )}
        >
          <Plus className="h-4 w-4 shrink-0" />
          {!collapsed && <span>New chat</span>}
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
              placeholder="Search conversations"
              className="h-9 rounded-lg border-border bg-background/40 pl-9 text-sm placeholder:text-muted-foreground/70"
            />
          </div>
        </div>
      )}

      {/* Lists */}
      <div className="mt-3 flex-1 overflow-y-auto px-2 pb-2">
        {!collapsed && favorites.length > 0 && (
          <Section title="Favorites">
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
          </Section>
        )}
        {!collapsed && (
          <Section title="Recent">
            {recents.length === 0 && (
              <div className="px-3 py-2 text-xs text-muted-foreground">No conversations yet</div>
            )}
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
          </Section>
        )}
        {collapsed &&
          conversations.slice(0, 8).map((c) => (
            <button
              key={c.id}
              onClick={() => onSelect(c.id)}
              className={cn(
                "mx-auto my-1 grid h-9 w-9 place-items-center rounded-lg text-muted-foreground transition hover:bg-accent hover:text-foreground",
                c.id === activeId && "bg-primary/15 text-primary"
              )}
              title={c.title}
            >
              <MessageSquare className="h-4 w-4" />
            </button>
          ))}
      </div>

      {/* Footer */}
      <div className="border-t border-border p-3">
        <button
          onClick={onOpenSettings}
          className={cn(
            "flex w-full items-center gap-2 rounded-lg px-2 py-2 text-sm text-muted-foreground transition hover:bg-accent hover:text-foreground",
            collapsed && "justify-center"
          )}
        >
          <Settings className="h-4 w-4 shrink-0" />
          {!collapsed && <span>Settings</span>}
        </button>
        <div
          className={cn(
            "mt-2 flex items-center gap-2 rounded-lg px-2 py-2",
            collapsed && "justify-center"
          )}
        >
          <div className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-gradient-to-br from-primary to-cyan text-xs font-semibold text-primary-foreground">
            DR
          </div>
          {!collapsed && (
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium">Dr. Rania Adel</div>
              <div className="truncate text-[11px] text-muted-foreground">Administrator</div>
            </div>
          )}
        </div>
      </div>

      {/* Collapse toggle */}
      <button
        onClick={onToggleCollapse}
        className="absolute -right-3 top-6 z-30 grid h-6 w-6 place-items-center rounded-full border border-border bg-card text-muted-foreground shadow-md transition hover:text-foreground"
        aria-label="Toggle sidebar"
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
    <div
      className={cn(
        "group relative flex items-center gap-2 rounded-lg px-3 py-2 text-sm transition cursor-pointer",
        active
          ? "bg-primary/15 text-foreground"
          : "text-muted-foreground hover:bg-accent hover:text-foreground"
      )}
      onClick={() => onSelect(conv.id)}
    >
      {active && (
        <span className="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-r bg-primary" />
      )}
      <MessageSquare className="h-3.5 w-3.5 shrink-0" />
      <span className="truncate flex-1">{conv.title}</span>
      <div className="hidden shrink-0 items-center gap-1 group-hover:flex">
        <button
          onClick={(e) => {
            e.stopPropagation();
            onFav(conv.id);
          }}
          className="grid h-6 w-6 place-items-center rounded hover:bg-background/40"
        >
          <Star
            className={cn(
              "h-3 w-3",
              conv.favorite ? "fill-warning text-warning" : "text-muted-foreground"
            )}
          />
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDelete(conv.id);
          }}
          className="grid h-6 w-6 place-items-center rounded text-muted-foreground hover:bg-background/40 hover:text-destructive"
        >
          <Trash2 className="h-3 w-3" />
        </button>
      </div>
    </div>
  );
}
