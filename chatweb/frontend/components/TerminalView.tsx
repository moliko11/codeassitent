"use client";
// xterm 终端渲染 Bash 输出(Phase 2 §2.4)。执行中闪烁光标,完成后写输出。
// 动态 import 使用(需要 DOM)。CSS 由 app/layout.tsx 顶部引入 xterm.css。
import { useEffect, useRef } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";

interface Props {
  text: string;
  running?: boolean;
}

export default function TerminalView({ text, running = false }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);

  // running 翻转时重建(执行前空终端 + 闪烁光标 → 完成后写输出)。
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const term = new Terminal({
      convertEol: true,
      cursorBlink: running,
      fontSize: 12,
      scrollback: 5000,
      theme: { background: "#0b0f1a", foreground: "#d4d4d4", cursor: "#569cd6" },
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(host);
    fit.fit();
    termRef.current = term;
    const ro = new ResizeObserver(() => fit.fit());
    ro.observe(host);
    return () => {
      ro.disconnect();
      term.dispose();
      termRef.current = null;
    };
  }, [running]);

  // text 变化 → 清屏重写
  useEffect(() => {
    const term = termRef.current;
    if (!term) return;
    term.clear();
    if (text) term.write(text);
  }, [text]);

  return (
    <div
      ref={hostRef}
      className="h-56 w-full overflow-hidden rounded-lg bg-[#0b0f1a] p-2"
      aria-label="终端输出"
    />
  );
}
