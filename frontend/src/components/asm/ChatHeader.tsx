import { Trash2, PanelRight, Sun, Moon } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";
import { MedAgentLogo } from "./MedAgentLogo";

interface Props {
  title: string;
  onClear: () => void;
  onToggleInfo: () => void;
  infoOpen: boolean;
}

export function ChatHeader({ title, onClear, onToggleInfo, infoOpen }: Props) {
  const [dark, setDark] = useState(true);

  const toggleTheme = () => {
    setDark((d) => {
      const next = !d;
      document.documentElement.classList.toggle("light-mode", !next);
      return next;
    });
  };

  return (
    <header className="flex items-center gap-3 border-b border-border bg-background/60 px-4 py-3 backdrop-blur">
      <div className="shrink-0">
        <MedAgentLogo size={28} noIntro className="[&_svg]:!block" />
      </div>
      <div className="grid min-w-0 flex-1 grid-cols-[minmax(0,1fr)_auto] items-center gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold">{title}</div>
          <div className="mt-0.5 flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-success pulse-ring" />
            <span className="text-[11px] text-muted-foreground">AI · Online</span>
          </div>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <IconBtn onClick={toggleTheme} title="Toggle theme">
          {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </IconBtn>
        <IconBtn onClick={onClear} title="Clear chat">
          <Trash2 className="h-4 w-4" />
        </IconBtn>
        <IconBtn onClick={onToggleInfo} title="Details panel" active={infoOpen}>
          <PanelRight className="h-4 w-4" />
        </IconBtn>
      </div>
    </header>
  );
}

function IconBtn({
  children,
  onClick,
  title,
  active,
}: {
  children: React.ReactNode;
  onClick: () => void;
  title: string;
  active?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      className={cn(
        "grid h-9 w-9 place-items-center rounded-lg text-muted-foreground transition hover:bg-accent hover:text-foreground",
        active && "bg-primary/15 text-primary"
      )}
    >
      {children}
    </button>
  );
}
