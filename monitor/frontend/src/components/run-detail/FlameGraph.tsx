// 火焰图:span 树按 parent_id 建树,垂直 icicle。Phase 3 §3.1 交互:
// - 单击选中 -> 下方 SpanDetail 详情面板;tool span 可「在消息流查看」跳转高亮
// - 双击聚焦子树(zoom 重根,宽度重新相对子树),提供「返回全貌」
// - 子 agent span(attrs.agent_id 非空)红边框 + [子],hover title 显示 name/duration/usage
import { useMemo, useState } from "react";
import { Undo2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/common/EmptyState";
import type { Span, Trace } from "@/lib/types";
import { FlameBar } from "./FlameBar";
import { SpanDetail } from "./SpanDetail";

interface Props {
  trace: Trace | null | undefined;
  onJumpToTranscript: (callId: string) => void;
}

export function FlameGraph({ trace, onJumpToTranscript }: Props) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focusId, setFocusId] = useState<string | null>(null);

  const { allRoots, runDur, byParent, spansById } = useMemo(() => {
    const byParent = new Map<string | null, Span[]>();
    const spansById = new Map<string, Span>();
    for (const s of trace?.spans ?? []) {
      const k = s.parent_id ?? null;
      const arr = byParent.get(k) ?? [];
      arr.push(s);
      byParent.set(k, arr);
      spansById.set(s.span_id, s);
    }
    const allRoots = byParent.get(null) ?? [];
    const runDur = Math.max(...(trace?.spans ?? []).map((s) => s.duration_ms ?? 0), 1);
    return { allRoots, runDur, byParent, spansById };
  }, [trace]);

  if (!trace || !trace.spans.length)
    return (
      <EmptyState
        title="无 trace"
        desc="崩了没 RunEnd,或 run 还在跑(observability-todo 坑2:trace.jsonl 是 RunEnd 整条覆盖写)"
      />
    );

  const focusSpan = focusId ? spansById.get(focusId) : null;
  // 聚焦时根 = 该 span,宽度参考也换成它(子树占满全宽);否则全 run 根 + runDur
  const displayRoots = focusSpan ? [focusSpan] : allRoots;
  const viewDur = focusSpan ? focusSpan.duration_ms || 1 : runDur;
  const selectedSpan = selectedId ? spansById.get(selectedId) : null;

  return (
    <div className="space-y-3">
      {focusSpan && (
        <div className="flex items-center gap-2 text-xs text-[var(--muted-foreground)]">
          <span className="truncate">
            聚焦于 <span className="font-mono text-[var(--foreground)]">{focusSpan.type} {focusSpan.name}</span>
          </span>
          <Button
            size="sm"
            variant="outline"
            className="ml-auto h-6 shrink-0 px-2 text-xs"
            onClick={() => setFocusId(null)}
          >
            <Undo2 className="h-3 w-3" /> 返回全貌
          </Button>
        </div>
      )}
      <div className="space-y-0.5 overflow-x-auto pb-2">
        {displayRoots.map((s) => (
          <FlameBar
            key={s.span_id}
            span={s}
            depth={0}
            runDur={viewDur}
            byParent={byParent}
            selected={selectedId === s.span_id}
            onSelect={setSelectedId}
            onZoom={(id) => {
              setSelectedId(id);
              setFocusId(id);
            }}
          />
        ))}
      </div>
      {selectedSpan && (
        <SpanDetail span={selectedSpan} onJumpToTranscript={onJumpToTranscript} />
      )}
    </div>
  );
}
