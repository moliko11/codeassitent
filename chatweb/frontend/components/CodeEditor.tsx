"use client";
// 只读代码查看器(Phase 2 §2.4)。Monaco 全本地(monacoSetup 装配 worker),无 CDN。
// 注意:模块级 import monacoSetup 有浏览器副作用,使用方必须 next/dynamic({ssr:false}) 加载本组件。
import "@/lib/monacoSetup";
import { Editor } from "@monaco-editor/react";

interface Props {
  value: string;
  language?: string;
  readOnly?: boolean;
  height?: string | number;
}

export default function CodeEditor({
  value,
  language = "plaintext",
  readOnly = true,
  height = "100%",
}: Props) {
  return (
    <Editor
      height={height}
      defaultLanguage={language}
      value={value}
      theme="vs-dark"
      options={{
        readOnly,
        minimap: { enabled: false },
        fontSize: 12,
        automaticLayout: true,
        wordWrap: "on",
        scrollBeyondLastLine: false,
        lineNumbersMinChars: 3,
      }}
    />
  );
}
