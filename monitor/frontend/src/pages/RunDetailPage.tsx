import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { useRun, useTrace, useTranscript, useSubagents } from "@/hooks/useQueries";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/common/EmptyState";
import { MetaPanel } from "@/components/run-detail/MetaPanel";
import { FlameGraph } from "@/components/run-detail/FlameGraph";
import { TranscriptStream } from "@/components/run-detail/TranscriptStream";
import { SubagentActivityList } from "@/components/run-detail/SubagentActivityList";
import { SystemPromptView } from "@/components/run-detail/SystemPromptView";
import { TokenBreakdown } from "@/components/run-detail/TokenBreakdown";
import { ContextSnapshotView } from "@/components/run-detail/ContextSnapshotView";
import { ApiError } from "@/lib/api";

export function RunDetailPage() {
  const { runId } = useParams();
  const runQ = useRun(runId ?? "");
  const traceQ = useTrace(runId ?? "");
  const transcriptQ = useTranscript(runId ?? "");
  const subagentsQ = useSubagents(runId ?? "");

  // 受控 tab + 火焰图跳转高亮(Phase 3 §3.1):「在消息流查看」-> 切 tab + 记 call_id
  const [tab, setTab] = useState("flame");
  const [highlightCallId, setHighlightCallId] = useState<string | null>(null);

  if (runQ.isLoading)
    return (
      <div className="p-6">
        <Skeleton className="h-64" />
      </div>
    );
  if (runQ.isError)
    return (
      <div className="p-6">
        <EmptyState title="加载失败" desc={(runQ.error as ApiError).message} />
      </div>
    );
  if (!runQ.data) return null;
  const { meta, report } = runQ.data;

  return (
    <div className="mx-auto max-w-7xl space-y-4 p-6">
      <div className="flex items-center gap-2">
        <Link
          to="/runs"
          className="text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
        >
          <ArrowLeft className="h-4 w-4" />
        </Link>
        <h1 className="font-mono text-xl font-semibold tracking-tight">
          {meta.run_id.slice(0, 8)}…
        </h1>
      </div>

      <MetaPanel meta={meta} report={report} trace={traceQ.data} />

      <Tabs value={tab} onValueChange={setTab} className="w-full">
        <TabsList>
          <TabsTrigger value="flame">火焰图</TabsTrigger>
          <TabsTrigger value="subagents">子 Agent</TabsTrigger>
          <TabsTrigger value="transcript">消息流</TabsTrigger>
          <TabsTrigger value="prompt">系统提示词</TabsTrigger>
          <TabsTrigger value="token">Token 明细</TabsTrigger>
          <TabsTrigger value="context">上下文快照</TabsTrigger>
        </TabsList>

        <TabsContent value="flame">
          <Card>
            <CardContent className="p-4">
              {traceQ.isLoading ? (
                <Skeleton className="h-48" />
              ) : (
                <FlameGraph
                  trace={traceQ.data}
                  onJumpToTranscript={(callId) => {
                    setHighlightCallId(callId);
                    setTab("transcript");
                  }}
                />
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="subagents">
          <Card>
            <CardContent className="p-4">
              {subagentsQ.isLoading ? (
                <Skeleton className="h-48" />
              ) : subagentsQ.isError ? (
                <EmptyState title="加载失败" desc={(subagentsQ.error as ApiError).message} />
              ) : (
                <SubagentActivityList activities={subagentsQ.data ?? []} />
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="transcript">
          <Card>
            <CardContent className="p-4">
              {transcriptQ.isLoading ? (
                <Skeleton className="h-48" />
              ) : transcriptQ.isError ? (
                <EmptyState title="加载失败" desc={(transcriptQ.error as ApiError).message} />
              ) : (
                <TranscriptStream
                  records={transcriptQ.data ?? []}
                  highlightCallId={highlightCallId}
                />
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="prompt">
          <Card>
            <CardContent className="p-4">
              <SystemPromptView prompt={meta.system_prompt} />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="token">
          <Card>
            <CardContent className="p-4">
              {traceQ.isLoading ? (
                <Skeleton className="h-48" />
              ) : (
                <TokenBreakdown trace={traceQ.data} />
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="context">
          <Card>
            <CardContent className="p-4">
              <ContextSnapshotView />
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
