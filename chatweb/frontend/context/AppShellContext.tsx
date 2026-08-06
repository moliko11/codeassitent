"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import {
  type Theme,
  applyThemeToDocument,
  getStoredTheme,
  getSystemTheme,
  setTheme as persistTheme,
} from "@/lib/theme";

/**
 * AppShellContext - client-side UI preferences (localStorage only, no backend).
 * Ported from DeepTutor's web/context/AppShellContext.tsx (trimmed: no i18n).
 *
 * Holds: theme, sidebar collapse, and code-block rendering prefs that
 * RichCodeBlock reads.
 */

type CodeBlockTheme = "oneDark" | "oneLight" | "github";

interface AppShellValue {
  theme: Theme;
  setTheme: (t: Theme) => void;
  sidebarCollapsed: boolean;
  setSidebarCollapsed: (v: boolean) => void;
  codeBlockTheme: CodeBlockTheme;
  setCodeBlockTheme: (t: CodeBlockTheme) => void;
  codeBlockShowLineNumbers: boolean;
  setCodeBlockShowLineNumbers: (v: boolean) => void;
  codeBlockWrapLongLines: boolean;
  setCodeBlockWrapLongLines: (v: boolean) => void;
}

const AppShellContext = createContext<AppShellValue | null>(null);

const COLLAPSED_KEY = "chat-template-sidebarCollapsed";
const CB_THEME_KEY = "chat-template-cbTheme";
const CB_LINES_KEY = "chat-template-cbLines";
const CB_WRAP_KEY = "chat-template-cbWrap";

function readBool(key: string, fallback: boolean): boolean {
  if (typeof window === "undefined") return fallback;
  const v = window.localStorage.getItem(key);
  return v === null ? fallback : v === "1";
}
function writeBool(key: string, v: boolean) {
  try {
    window.localStorage.setItem(key, v ? "1" : "0");
  } catch {
    /* ignore */
  }
}
function readCbTheme(): CodeBlockTheme {
  if (typeof window === "undefined") return "oneDark";
  const v = window.localStorage.getItem(CB_THEME_KEY);
  return v === "oneDark" || v === "oneLight" || v === "github" ? v : "oneDark";
}

export function AppShellProvider({ children }: { children: ReactNode }) {
  // Start with defaults that match SSR; hydrate from localStorage after mount.
  const [theme, setThemeState] = useState<Theme>("snow");
  const [sidebarCollapsed, setSidebarCollapsedState] = useState(false);
  const [codeBlockTheme, setCodeBlockThemeState] = useState<CodeBlockTheme>("oneDark");
  const [codeBlockShowLineNumbers, setCodeBlockShowLineNumbersState] = useState(false);
  const [codeBlockWrapLongLines, setCodeBlockWrapLongLinesState] = useState(false);

  useEffect(() => {
    // Hydrate client-only prefs after the SSR-safe first render.
    const storedTheme = getStoredTheme();
    const initialTheme = storedTheme ?? getSystemTheme();
    applyThemeToDocument(initialTheme);
    setThemeState(initialTheme);

    setSidebarCollapsedState(readBool(COLLAPSED_KEY, false));
    setCodeBlockThemeState(readCbTheme());
    setCodeBlockShowLineNumbersState(readBool(CB_LINES_KEY, false));
    setCodeBlockWrapLongLinesState(readBool(CB_WRAP_KEY, false));
  }, []);

  const setTheme = useCallback((t: Theme) => {
    persistTheme(t); // applyThemeToDocument + localStorage (lib/theme.ts)
    setThemeState(t);
  }, []);

  const setSidebarCollapsed = useCallback((v: boolean) => {
    writeBool(COLLAPSED_KEY, v);
    setSidebarCollapsedState(v);
  }, []);

  const setCodeBlockTheme = useCallback((t: CodeBlockTheme) => {
    try {
      window.localStorage.setItem(CB_THEME_KEY, t);
    } catch {
      /* ignore */
    }
    setCodeBlockThemeState(t);
  }, []);

  const setCodeBlockShowLineNumbers = useCallback((v: boolean) => {
    writeBool(CB_LINES_KEY, v);
    setCodeBlockShowLineNumbersState(v);
  }, []);

  const setCodeBlockWrapLongLines = useCallback((v: boolean) => {
    writeBool(CB_WRAP_KEY, v);
    setCodeBlockWrapLongLinesState(v);
  }, []);

  return (
    <AppShellContext.Provider
      value={{
        theme,
        setTheme,
        sidebarCollapsed,
        setSidebarCollapsed,
        codeBlockTheme,
        setCodeBlockTheme,
        codeBlockShowLineNumbers,
        setCodeBlockShowLineNumbers,
        codeBlockWrapLongLines,
        setCodeBlockWrapLongLines,
      }}
    >
      {children}
    </AppShellContext.Provider>
  );
}

export function useAppShell(): AppShellValue {
  const ctx = useContext(AppShellContext);
  if (!ctx) throw new Error("useAppShell must be used within AppShellProvider");
  return ctx;
}
