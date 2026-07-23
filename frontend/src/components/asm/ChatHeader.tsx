import { ChevronLeft, ChevronRight, Moon, Sun } from "lucide-react";
import { cn } from "@/lib/utils";
import { MedAgentLogo } from "./MedAgentLogo";
import { tr } from "@/locales/tr";
import { useTheme } from "@/hooks/use-theme";

interface Props {
  title: string;
  onToggleInfo: () => void;
  infoOpen: boolean;
}

export function ChatHeader({ title, onToggleInfo, infoOpen }: Props) {
  const { theme, toggleTheme } = useTheme();

  return (
    <header className="flex h-16 shrink-0 items-center gap-3 border-b border-border bg-background/60 px-4 backdrop-blur">
      <div className="shrink-0">
        <MedAgentLogo size={34} noIntro />
      </div>
      <div className="grid min-w-0 flex-1 grid-cols-[minmax(0,1fr)_auto] items-center gap-3">
        <div className="min-w-0">
          <div className="truncate text-[15px] font-semibold leading-5 text-foreground">
            {title}
          </div>
          <div className="mt-0.5 flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-success pulse-ring" />
            <span className="text-xs leading-4 text-muted-foreground">{tr.header.online}</span>
          </div>
        </div>
      </div>
      <IconBtn onClick={toggleTheme} title={tr.header.toggleTheme}>
        {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
      </IconBtn>
      <IconBtn onClick={onToggleInfo} title={tr.header.detailsPanel} active={infoOpen}>
        {infoOpen ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
      </IconBtn>
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
      aria-label={title}
      aria-pressed={active}
      className={cn(
        "grid h-9 w-9 place-items-center rounded-lg text-muted-foreground transition hover:bg-accent hover:text-foreground",
        active && "bg-primary/15 text-primary",
      )}
    >
      {children}
    </button>
  );
}
