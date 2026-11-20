import { useCallback, useEffect, useState } from "react";

export type Theme = "system" | "light" | "dark";
const KEY = "yaver.theme";
const ORDER: Theme[] = ["system", "light", "dark"];

export function storedTheme(): Theme {
  try {
    const value = localStorage.getItem(KEY);
    // dark first: nothing stored (or anything unknown) -> dark
    return value === "light" || value === "system" ? value : "dark";
  } catch {
    return "dark";
  }
}

function prefersDark(): boolean {
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export function applyTheme(theme: Theme): void {
  const dark = theme === "dark" || (theme === "system" && prefersDark());
  document.documentElement.classList.toggle("dark", dark);
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute("content", dark ? "#060914" : "#eef2ff");
}

export function useTheme(): { theme: Theme; cycle: () => void } {
  const [theme, setTheme] = useState<Theme>(storedTheme);

  useEffect(() => {
    applyTheme(theme);
    try {
      localStorage.setItem(KEY, theme);
    } catch {
      // private mode: the choice just isn't remembered
    }
    if (theme !== "system") return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const follow = (): void => {
      applyTheme("system");
    };
    media.addEventListener("change", follow);
    return () => {
      media.removeEventListener("change", follow);
    };
  }, [theme]);

  const cycle = useCallback(() => {
    setTheme((current) => ORDER[(ORDER.indexOf(current) + 1) % ORDER.length] ?? "system");
  }, []);

  return { theme, cycle };
}
