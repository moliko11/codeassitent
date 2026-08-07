// 文件路径 → Monaco 语言(Phase 2 §2.4)。只读查看器只需 tokenize,默认 plaintext。
const EXT_TO_LANG: Record<string, string> = {
  py: "python",
  js: "javascript", jsx: "javascript", mjs: "javascript", cjs: "javascript",
  ts: "typescript", tsx: "typescript",
  json: "json",
  html: "html", htm: "html",
  css: "css", scss: "scss", less: "less",
  md: "markdown",
  yaml: "yaml", yml: "yaml",
  xml: "xml", svg: "xml",
  sh: "shell", bash: "shell", bat: "bat", ps1: "powershell",
  java: "java", kt: "kotlin", go: "go", rs: "rust",
  c: "c", h: "c", cpp: "cpp", hpp: "cpp", cc: "cpp", cs: "csharp",
  rb: "ruby", php: "php", sql: "sql",
  toml: "ini", ini: "ini", cfg: "ini",
  txt: "plaintext", log: "plaintext", env: "plaintext", lock: "plaintext",
};

/** 取路径扩展名对应语言;无扩展名/未知 -> plaintext。 */
export function languageFromPath(path: string): string {
  const base = path.split(/[\\/]/).pop() ?? "";
  const idx = base.lastIndexOf(".");
  if (idx <= 0) return "plaintext";
  const ext = base.slice(idx + 1).toLowerCase();
  return EXT_TO_LANG[ext] ?? "plaintext";
}
