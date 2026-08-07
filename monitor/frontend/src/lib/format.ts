// 格式化工具(从旧 dashboard.html 移植 + 增强)+ 系统提示词切分

export function fmtTs(ts: number | null | undefined): string {
  if (!ts || ts <= 0) return "-";
  const d = new Date(ts * 1000);
  return isNaN(d.getTime()) ? "-" : d.toLocaleString("zh-CN", { hour12: false });
}

export function fmtDate(ts: number | null | undefined): string {
  if (!ts || ts <= 0) return "-";
  const d = new Date(ts * 1000);
  return isNaN(d.getTime()) ? "-" : d.toLocaleDateString("zh-CN");
}

export function fmtDur(ms: number | null | undefined): string {
  if (ms == null) return "-";
  if (ms < 1000) return Math.round(ms) + "ms";
  if (ms < 60000) return (ms / 1000).toFixed(1) + "s";
  const m = Math.floor(ms / 60000);
  const s = Math.round((ms % 60000) / 1000);
  return `${m}m${s}s`;
}

export function fmtToken(n: number | null | undefined): string {
  if (n == null) return "-";
  if (n < 1000) return String(n);
  if (n < 1_000_000) return (n / 1000).toFixed(1) + "k";
  return (n / 1_000_000).toFixed(2) + "M";
}

export function fmtPct(r: number | null | undefined, fallback = "-"): string {
  if (r == null || isNaN(r)) return fallback;
  return (r * 100).toFixed(0) + "%";
}

/** cached / input 命中率;input=0 返回 0 */
export function cacheHitRate(cached: number, input: number): number {
  return input ? cached / input : 0;
}

export function shortId(id: string | null | undefined, n = 8): string {
  if (!id) return "-";
  return id.length > n ? id.slice(0, n) + "…" : id;
}

/** 把系统提示词按 `## ` 标题分层(intro + sections),对齐旧 dashboard.html splitSections。
 *  /api/system_prompt 后端已切好;run_meta.system_prompt 用本函数前端切。 */
export function splitSections(text: string): {
  intro: string;
  sections: { title: string; body: string }[];
} {
  const intro: string[] = [];
  const sections: { title: string; body: string[] }[] = [];
  let cur: { title: string; body: string[] } | null = null;
  for (const line of (text || "").split("\n")) {
    if (line.startsWith("## ")) {
      if (cur) sections.push(cur);
      cur = { title: line.slice(3).trim(), body: [] };
    } else if (cur === null) {
      intro.push(line);
    } else {
      cur.body.push(line);
    }
  }
  if (cur) sections.push(cur);
  return {
    intro: intro.join("\n").trim(),
    sections: sections.map((s) => ({ title: s.title, body: s.body.join("\n").trim() })),
  };
}
