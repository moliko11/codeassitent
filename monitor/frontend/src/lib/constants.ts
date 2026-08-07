import type { SpanType } from "./types";

// span type -> 配色(火焰图条 + 徽标),对齐旧 dashboard.html .t-* + indigo 主色系
export const SPAN_TYPE_META: Record<string, { label: string; bg: string; text: string }> = {
  run: { label: "run", bg: "bg-indigo-500", text: "text-white" },
  step: { label: "step", bg: "bg-emerald-500", text: "text-white" },
  tool: { label: "tool", bg: "bg-amber-500", text: "text-white" },
  guardrail: { label: "guardrail", bg: "bg-rose-500", text: "text-white" },
  approval: { label: "approval", bg: "bg-violet-500", text: "text-white" },
};

export function spanTypeMeta(type: string) {
  return SPAN_TYPE_META[type] ?? { label: type, bg: "bg-zinc-400", text: "text-white" };
}

// status -> 徽标语义色(对齐旧 dashboard.html .b-*)
export type Tone = "success" | "warn" | "danger" | "muted";
const STATUS_TONE: Record<string, Tone> = {
  completed: "success",
  failed: "danger",
  max_steps_exceeded: "danger",
  running: "warn",
  waiting_tool: "warn",
  waiting_approval: "warn",
  cancelled: "muted",
  unknown: "muted",
};

export function statusTone(status: string): Tone {
  return STATUS_TONE[status] ?? "muted";
}

export const TONE_CLASS: Record<Tone, string> = {
  success: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-400",
  warn: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-400",
  danger: "bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-400",
  muted: "bg-zinc-100 text-zinc-600 dark:bg-zinc-500/15 dark:text-zinc-400",
};

// 动态会话级系统提示词段(标题关键词匹配,标"动态·会话级")
const DYNAMIC_SECTION_KEYWORDS = ["语言", "环境", "仓库", "工具结果清理", "Token预算", "Token 预算"];

export function isDynamicSection(title: string): boolean {
  return DYNAMIC_SECTION_KEYWORDS.some((k) => title.includes(k));
}

// Recharts 语义色
export const CHART_COLORS = {
  input: "#6366f1",   // indigo-500
  output: "#10b981",  // emerald-500
  cached: "#f59e0b",  // amber-500
  primary: "#4f46e5",
  muted: "#a1a1aa",
  ok: "#10b981",
  err: "#ef4444",
};
