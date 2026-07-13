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

export function SettingsDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const [temp, setTemp] = useState([0.7]);
  const [maxTokens, setMaxTokens] = useState([2048]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="glass max-w-lg border-border">
        <DialogHeader>
          <DialogTitle>Settings</DialogTitle>
          <DialogDescription>Customize your ASM AI experience.</DialogDescription>
        </DialogHeader>

        <div className="mt-2 flex flex-col gap-5">
          <Field label="Theme">
            <Select defaultValue="dark">
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="dark">Dark (default)</SelectItem>
                <SelectItem value="light">Light</SelectItem>
                <SelectItem value="system">System</SelectItem>
              </SelectContent>
            </Select>
          </Field>

          <Field label="Language">
            <Select defaultValue="en">
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="en">English</SelectItem>
                <SelectItem value="ar">العربية</SelectItem>
                <SelectItem value="fr">Français</SelectItem>
              </SelectContent>
            </Select>
          </Field>

          <Field label="Model">
            <Select defaultValue="asm-pro">
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="asm-pro">ASM Pro · balanced</SelectItem>
                <SelectItem value="asm-fast">ASM Fast · low latency</SelectItem>
                <SelectItem value="asm-deep">ASM Deep · reasoning</SelectItem>
              </SelectContent>
            </Select>
          </Field>

          <Field label={`Temperature · ${temp[0].toFixed(2)}`}>
            <Slider value={temp} onValueChange={setTemp} min={0} max={1} step={0.05} />
          </Field>

          <Field label={`Max tokens · ${maxTokens[0]}`}>
            <Slider value={maxTokens} onValueChange={setMaxTokens} min={256} max={8192} step={128} />
          </Field>

          <Field label="Display name">
            <Input defaultValue="Dr. Rania Adel" />
          </Field>

          <button className="flex items-center justify-center gap-2 rounded-xl border border-destructive/40 bg-destructive/10 px-4 py-2.5 text-sm font-medium text-destructive transition hover:bg-destructive/20">
            <LogOut className="h-4 w-4" />
            Log out
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
