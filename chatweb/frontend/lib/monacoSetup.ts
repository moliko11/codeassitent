// Monaco 本地 worker 装配(Phase 2 §2.4)。全本地无 CDN。
// 注意:Next 15 webpack 不支持 Vite 的 `?worker` 默认导出语法(会报 "does not contain a
// default export"),用 webpack 原生 worker 写法 `new Worker(new URL(..., import.meta.url))`,
// 构建期把 worker 文件作为独立 chunk 发射(out/_next/static 有 worker chunk)。
// 只留 editor.worker:本应用是只读查看/对比,Monarch 高亮 tokenize 走 editor worker,
// 不需要 ts/json/css/html 语言服务的 intellisense(减负,方案里标注过)。
import * as monaco from "monaco-editor";
import { loader } from "@monaco-editor/react";

self.MonacoEnvironment = {
  getWorker: () => new Worker(new URL("monaco-editor/esm/vs/editor/editor.worker.js", import.meta.url)),
};

// 让 @monaco-editor/react 用本地 monaco 包,不走默认 CDN 加载。
loader.config({ monaco });
