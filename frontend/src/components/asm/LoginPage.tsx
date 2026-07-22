import { motion } from "motion/react";
import { MedAgentLogo } from "./MedAgentLogo";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useState } from "react";
import { tr } from "@/locales/tr";

interface Props {
  onLogin?: () => void;
}

export function LoginPage({ onLogin }: Props) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onLogin?.();
  };

  return (
    <div className="relative flex min-h-screen w-full items-center justify-center overflow-hidden bg-background">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-50"
        style={{ background: "var(--gradient-hero)" }}
      />

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
        className="relative z-10 w-full max-w-sm px-6"
      >
        <div className="flex flex-col items-center">
          <MedAgentLogo size={72} />
          <h1 className="mt-5 text-xl font-semibold tracking-tight text-foreground">Med Agent</h1>
          <p className="mt-1 text-sm text-muted-foreground">{tr.login.tagline}</p>
        </div>

        <form onSubmit={handleSubmit} className="mt-10 flex flex-col gap-5">
          <div className="flex flex-col gap-2">
            <Label
              htmlFor="login-email"
              className="text-xs uppercase tracking-wider text-muted-foreground"
            >
              {tr.login.email}
            </Label>
            <Input
              id="login-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="name@healthcare.gov"
              className="h-11 rounded-xl border-border bg-card px-4 text-sm"
              autoComplete="email"
            />
          </div>

          <div className="flex flex-col gap-2">
            <Label
              htmlFor="login-password"
              className="text-xs uppercase tracking-wider text-muted-foreground"
            >
              {tr.login.password}
            </Label>
            <Input
              id="login-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={tr.login.passwordPlaceholder}
              className="h-11 rounded-xl border-border bg-card px-4 text-sm"
              autoComplete="current-password"
            />
          </div>

          <Button
            type="submit"
            disabled={!email || !password}
            className="h-11 w-full rounded-xl bg-gradient-to-r from-primary to-cyan text-sm font-medium text-primary-foreground shadow-[var(--shadow-glow)] transition hover:opacity-90 disabled:opacity-40"
          >
            {tr.login.signIn}
          </Button>

          <p className="text-center text-xs text-muted-foreground/70">{tr.login.protectedBy}</p>
        </form>
      </motion.div>
    </div>
  );
}
