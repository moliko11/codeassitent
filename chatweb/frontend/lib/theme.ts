/**
 * Theme persistence utilities (ported from DeepTutor's web/lib/theme.ts).
 * localStorage-backed, four themes: light (Cream), dark, glass, snow (Default).
 */

export type Theme = "light" | "dark" | "glass" | "snow";

export const THEME_STORAGE_KEY = "chat-template-theme";

export function getStoredTheme(): Theme | null {
  if (typeof window === "undefined") return null;
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === "light" || stored === "dark" || stored === "glass" || stored === "snow") {
      return stored;
    }
  } catch {
    /* localStorage may be disabled */
  }
  return null;
}

export function getSystemTheme(): Theme {
  if (typeof window === "undefined") return "snow";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "snow";
}

export function applyThemeToDocument(theme: Theme): void {
  if (typeof document === "undefined") return;
  const html = document.documentElement;
  html.classList.remove("dark", "theme-glass", "theme-snow");
  if (theme === "dark") html.classList.add("dark");
  else if (theme === "glass") html.classList.add("dark", "theme-glass");
  else if (theme === "snow") html.classList.add("theme-snow");
  // "light" (Cream) needs no class - it is the :root default.
}

export function setTheme(theme: Theme): void {
  applyThemeToDocument(theme);
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    /* ignore */
  }
}

export function initializeTheme(): Theme {
  const stored = getStoredTheme();
  if (stored) {
    applyThemeToDocument(stored);
    return stored;
  }
  const system = getSystemTheme();
  applyThemeToDocument(system);
  return system;
}
