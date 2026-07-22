import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { LogOut } from "lucide-react";
import { useState } from "react";
import { tr } from "@/locales/tr";

export function SettingsDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const [temp, setTemp] = useState([0.7]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="glass max-w-lg border-border">
        <DialogHeader>
          <DialogTitle>{tr.settingsDialog.title}</DialogTitle>
          <DialogDescription>{tr.settingsDialog.description}</DialogDescription>
        </DialogHeader>

        <div className="mt-2 flex flex-col gap-5">
          <Field label={tr.settingsDialog.language}>
            <Select defaultValue="tr">
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="tr">Türkçe</SelectItem>
                <SelectItem value="en">English</SelectItem>
              </SelectContent>
            </Select>
          </Field>

          <Field label={`${tr.settingsDialog.temperature} · ${temp[0].toFixed(2)}`}>
            <Slider value={temp} onValueChange={setTemp} min={0} max={1} step={0.05} />
          </Field>

          <Field label={tr.settingsDialog.displayName}>
            <Input defaultValue="" />
          </Field>

          <button className="flex items-center justify-center gap-2 rounded-xl border border-destructive/40 bg-destructive/10 px-4 py-2.5 text-sm font-medium text-destructive transition hover:bg-destructive/20">
            <LogOut className="h-4 w-4" />
            {tr.settingsDialog.logOut}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <Label className="text-xs uppercase tracking-wider text-muted-foreground">{label}</Label>
      {children}
    </div>
  );
}
