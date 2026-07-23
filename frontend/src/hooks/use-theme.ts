import { useCallback, useEffect, useState } from "react";

export type Theme = "light" | "dark";

export const THEME_STORAGE_KEY = "asm-theme";

/** Inline, must run synchronously in <head> before first paint to avoid a
 * light->dark flash on reload — see routes/__root.tsx RootShell. */
export const THEME_FOUC_GUARD_SCRIPT = `(function(){try{var t=localStorage.getItem(${JSON.stringify(
  THEME_STORAGE_KEY,
)});if(t==="dark"){document.documentElement.classList.add("dark");}}catch(e){}})();`;

function applyThemeClass(theme: Theme) {
  document.documentElement.classList.toggle("dark", theme === "dark");
}

/**
 * One-click light/dark theme toggle. Defaults to "light" on both the server
 * and the very first client render (matching THEME_FOUC_GUARD_SCRIPT's
 * default) so there is no hydration mismatch; the real persisted preference
 * is read once after mount and applied — a one-frame correction, never a
 * console warning.
 */
export function useTheme() {
  const [theme, setThemeState] = useState<Theme>("light");

  useEffect(() => {
    const current = document.documentElement.classList.contains("dark") ? "dark" : "light";
    setThemeState(current);
  }, []);

  const setTheme = useCallback((next: Theme) => {
    applyThemeClass(next);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      /* localStorage unavailable (private mode/quota) — theme still applies for this session */
    }
    setThemeState(next);
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme(theme === "dark" ? "light" : "dark");
  }, [theme, setTheme]);

  return { theme, setTheme, toggleTheme };
}
