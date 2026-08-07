// ⏳ 观测性预留(observability-todo A/B):每轮 context 快照 + 装配可视化。
// 数据未就绪(ContextBuilder 未落 context_snapshots.jsonl),先空态占位。
import { EmptyState } from "@/components/common/EmptyState";
import { Layers } from "lucide-react";

export function ContextSnapshotView() {
  return (
    <EmptyState
      icon={Layers}
      title="上下文快照(观测性预留)"
      desc="待 ContextBuilder.build 输出落 context_snapshots.jsonl(observability-todo A),后端加 /api/runs/{id}/context 后,此处展示每轮上下文装配:消息按 origin 分层(system/memory/cleared/budgeted/compact_summary/plan_step)+ 每层 token 占比。这是对标 Langfuse 的差异点。"
    />
  );
}
