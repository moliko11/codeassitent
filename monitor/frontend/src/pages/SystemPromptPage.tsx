import { useSystemPrompt } from "@/hooks/useQueries";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/common/EmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import { isDynamicSection } from "@/lib/constants";
import { ApiError } from "@/lib/api";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function SystemPromptPage() {
  const q = useSystemPrompt();
  return (
    <div className="mx-auto max-w-4xl space-y-4 p-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">系统提示词(分层)</h1>
        <p className="text-sm text-[var(--muted-foreground)]">
          源:AgentConfig().system_prompt(静态默认版)· {q.data?.sections.length ?? 0} 段
        </p>
      </div>

      {q.isLoading ? (
        <div className="space-y-3">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-24" />)}</div>
      ) : q.isError ? (
        <EmptyState title="加载失败" desc={(q.error as ApiError).message} />
      ) : !q.data ? null : (
        <>
          <Card className="border-l-4 border-l-amber-400">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">引言</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="prose-sm">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{q.data.intro}</ReactMarkdown>
              </div>
            </CardContent>
          </Card>
          {q.data.sections.map((s, i) => (
            <Card key={i} className="border-l-4 border-l-indigo-500">
              <CardHeader className="flex-row items-center justify-between pb-2">
                <CardTitle className="text-sm">
                  {i + 1}. {s.title}
                </CardTitle>
                {isDynamicSection(s.title) && (
                  <Badge variant="secondary" className="text-[10px]">
                    动态·会话级
                  </Badge>
                )}
              </CardHeader>
              <CardContent>
                <div className="prose-sm">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{s.body}</ReactMarkdown>
                </div>
              </CardContent>
            </Card>
          ))}
        </>
      )}
    </div>
  );
}
