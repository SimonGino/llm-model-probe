import { useEffect, useState } from "react";

export type Theme = "light" | "dim" | "dark";
const KEY = "lmp-theme";

function read(): Theme {
  if (typeof localStorage === "undefined") return "light";
  const v = localStorage.getItem(KEY);
  if (v === "light" || v === "dim" || v === "dark") return v;
  return "light";
}

function apply(t: Theme) {
  if (typeof document === "undefined") return;
  document.documentElement.dataset.theme = t;
}

export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(read);
  useEffect(() => {
    apply(theme);
    try {
      localStorage.setItem(KEY, theme);
    } catch {
      // ignore (private browsing)
    }
  }, [theme]);
  return [theme, setTheme];
}
