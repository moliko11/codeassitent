// 消息流:按时间顺序;assistant 多 tool_calls = 并行批次;tool_result 折叠;subagent 徽标;搜索。
import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import { TranscriptItem } from "./TranscriptItem";
import { EmptyState } from "@/components/common/EmptyState";
import type { TranscriptRecord } from "@/lib/types";

export function TranscriptStream({ records }: { records: TranscriptRecord[] }) {
  const [q, setQ] = useState("");

  const filtered = useMemo(() => {
    if (!q.trim()) return records;
    const k = q.toLowerCase();
    return records.filter((r) => {
      const text = (r.content || r.text || "").toLowerCase();
      const tools = (r.tool_calls || []).map((tc) => tc.tool_name).join(" ").toLowerCase();
      const res = r.result
        ? `${r.result.tool_name} ${typeof r.result.data === "string" ? r.result.data : JSON.stringify(r.result.data ?? "")}`
        : "";
      return (text + " " + tools + " " + res).toLowerCase().includes(k);
    });
  }, [records, q]);

  if (!records.length) return <EmptyState title="无消息" />;

  return (
    <div className="space-y-1">
      <div className="sticky top-0 z-10 bg-[var(--card)] pb-2">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--muted-foreground)]" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="搜索消息 / 工具…"
            className="h-8 w-full rounded-md border border-[var(--border)] bg-transparent pl-8 pr-3 text-xs outline-none focus:ring-2 focus:ring-[var(--ring)]"
          />
        </div>
        <div className="mt-1 text-[11px] text-[var(--muted-foreground)]">
          共 {records.length} 条{q.trim() && ` · 匹配 ${filtered.length}`}
        </div>
      </div>
      {filtered.map((r, i) => (
        <TranscriptItem key={r.uuid ?? i} record={r} />
      ))}
      {filtered.length === 0 && <EmptyState title="无匹配" />}
    </div>
  );
}
