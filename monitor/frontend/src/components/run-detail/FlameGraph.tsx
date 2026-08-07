// 火焰图:span 树按 parent_id 建树,垂直 icicle(每行一个 span,indent=深度,宽∝duration/runDur)。
// 子 agent span(attrs.agent_id 非空)红边框 + [子]。hover title 显示 name/duration/usage。
import { useMemo } from "react";
import { EmptyState } from "@/components/common/EmptyState";
import type { Span, Trace } from "@/lib/types";
import { FlameBar } from "./FlameBar";

export function FlameGraph({ trace }: { trace: Trace | null | undefined }) {
  const { roots, runDur, byParent } = useMemo(() => {
    const byParent = new Map<string | null, Span[]>();
    for (const s of trace?.spans ?? []) {
      const k = s.parent_id ?? null;
      const arr = byParent.get(k) ?? [];
      arr.push(s);
      byParent.set(k, arr);
    }
    const roots = byParent.get(null) ?? [];
    const runDur = Math.max(...(trace?.spans ?? []).map((s) => s.duration_ms ?? 0), 1);
    return { roots, runDur, byParent };
  }, [trace]);

  if (!trace || !trace.spans.length)
    return (
      <EmptyState
        title="无 trace"
        desc="崩了没 RunEnd,或 run 还在跑(observability-todo 坑2:trace.jsonl 是 RunEnd 整条覆盖写)"
      />
    );

  return (
    <div className="space-y-0.5 overflow-x-auto pb-2">
      {roots.map((s) => (
        <FlameBar
          key={s.span_id}
          span={s}
          depth={0}
          runDur={runDur}
          byParent={byParent}
        />
      ))}
    </div>
  );
}
