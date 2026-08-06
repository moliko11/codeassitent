"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import RichCodeBlock from "./RichCodeBlock";
import { cn } from "@/lib/cn";

/**
 * MarkdownRenderer - renders assistant markdown with GFM (tables, task lists,
 * strikethrough) and syntax-highlighted code blocks. Uses the .prose / .md-
 * renderer styles in globals.css.
 *
 * Ported concept from DeepTutor's MarkdownRenderer + RichMarkdownRenderer.
 */
export default function MarkdownRenderer({
  content,
  className,
}: {
  content: string;
  className?: string;
}) {
  return (
    <div className={cn("md-renderer prose", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // Let RichCodeBlock be the code container; strip the default <pre>.
          pre: ({ children }) => <>{children}</>,
          code(props) {
            const { className: cls, children } = props as {
              className?: string;
              children?: React.ReactNode;
            };
            const match = /language-(\w+)/.exec(cls || "");
            if (match) {
              return (
                <RichCodeBlock
                  raw={String(children ?? "").replace(/\n$/, "")}
                  lang={match[1]}
                />
              );
            }
            return <code className="md-inline-code">{children}</code>;
          },
          a: ({ children, ...props }) => (
            <a target="_blank" rel="noreferrer noopener" {...props}>
              {children}
            </a>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
