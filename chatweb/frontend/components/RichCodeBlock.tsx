"use client";

import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark, oneLight } from "react-syntax-highlighter/dist/esm/styles/prism";
import { useAppShell } from "@/context/AppShellContext";

const MONOSPACE =
  'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace';
const PLAIN_LANGS = new Set(["", "text", "txt", "plain", "plaintext", "none"]);

/**
 * RichCodeBlock - syntax-highlighted code block (Prism).
 * Ported from DeepTutor's web/components/common/RichCodeBlock.tsx (trimmed).
 * Reads line-number / wrap preferences from AppShellContext.
 */
export default function RichCodeBlock({
  raw,
  lang,
  className,
}: {
  raw: string;
  lang: string;
  className?: string;
}) {
  const { codeBlockTheme, codeBlockShowLineNumbers, codeBlockWrapLongLines } =
    useAppShell();

  const normalizedLang = (lang || "").toLowerCase();
  const isPlain = PLAIN_LANGS.has(normalizedLang);
  const style = codeBlockTheme === "oneLight" ? oneLight : oneDark;

  // Pull the theme's background/foreground so the header bar matches.
  const preStyle = (style["pre[class*=\"language-\"]"] as React.CSSProperties) || {};
  const backgroundColor = (preStyle.background as string) || "#1f2937";
  const textColor = (preStyle.color as string) || "#e5e7eb";

  return (
    <div
      className={`md-code-block overflow-hidden rounded-xl border border-[var(--border)] ${className || ""}`}
      style={{ backgroundColor, color: textColor }}
    >
      {!isPlain ? (
        <div
          className="border-b border-[var(--border)] px-3 py-2 text-[11px] font-medium uppercase tracking-wider"
          style={{ color: textColor, opacity: 0.8 }}
        >
          {normalizedLang}
        </div>
      ) : null}
      <SyntaxHighlighter
        language={isPlain ? "text" : normalizedLang}
        style={style}
        PreTag="pre"
        customStyle={{
          margin: 0,
          borderRadius: 0,
          background: backgroundColor,
          color: textColor,
          padding: "1rem",
          fontSize: "0.875rem",
          lineHeight: "1.7",
          overflowX: codeBlockWrapLongLines ? "hidden" : "auto",
          whiteSpace: codeBlockWrapLongLines ? "pre-wrap" : "pre",
          wordWrap: codeBlockWrapLongLines ? "break-word" : "normal",
        }}
        codeTagProps={{
          className: "md-code-block__code",
          style: { fontFamily: MONOSPACE },
        }}
        showLineNumbers={codeBlockShowLineNumbers}
        wrapLongLines={codeBlockWrapLongLines}
      >
        {raw}
      </SyntaxHighlighter>
    </div>
  );
}
