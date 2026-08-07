// 系统提示词管理页(Phase 3 §3.3):分层查看 + 编辑保存到 persist/system_prompt.md + 恢复默认。
// 编辑用等宽 textarea(细节可简化,不引 Monaco)。
import { useEffect, useState } from "react";
import { Pencil, Save, RotateCcw, X } from "lucide-react";
import { useSystemPrompt, useSaveSystemPrompt, useResetSystemPrompt } from "@/hooks/useQueries";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/common/EmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import { isDynamicSection } from "@/lib/constants";
import { ApiError } from "@/lib/api";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function SystemPromptPage() {
  const q = useSystemPrompt();
  const saveMut = useSaveSystemPrompt();
  const resetMut = useResetSystemPrompt();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  // 进入编辑模式时拷当前 raw;保存/恢复刷新后(非编辑态)同步 draft
  useEffect(() => {
    if (!editing && q.data) setDraft(q.data.raw);
  }, [q.data, editing]);

  const source = q.data?.source;

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-6">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">系统提示词(分层)</h1>
          <p className="text-sm text-[var(--muted-foreground)]">
            源:AgentConfig().system_prompt(静态默认版)· {q.data?.sections.length ?? 0} 段
          </p>
        </div>
        {!editing && (
          <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
            <Pencil className="h-3 w-3" /> 编辑
          </Button>
        )}
      </div>

      {q.isLoading ? (
        <div className="space-y-3">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-24" />)}</div>
      ) : q.isError ? (
        <EmptyState title="加载失败" desc={(q.error as ApiError).message} />
      ) : !q.data ? null : editing ? (
        <Card>
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm">编辑原始文本</CardTitle>
              <Badge variant={source === "override" ? "secondary" : "outline"} className="text-[10px]">
                {source === "override" ? "会话级覆写中" : "默认静态版"}
              </Badge>
            </div>
            <p className="text-[11px] text-[var(--muted-foreground)]">
              保存到 code/persist/system_prompt.md(GET 与后续会话读取);「恢复默认」删掉该文件回退静态版
            </p>
          </CardHeader>
          <CardContent className="space-y-3">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              spellCheck={false}
              className="h-96 w-full resize-y rounded-md border border-[var(--border)] bg-transparent p-3 font-mono text-xs leading-relaxed outline-none focus:ring-2 focus:ring-[var(--ring)]"
            />
            <div className="flex items-center gap-2">
              <span className="text-[11px] text-[var(--muted-foreground)]">{draft.length} chars</span>
              <div className="ml-auto flex gap-2">
                <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
                  <X className="h-3 w-3" /> 取消
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => resetMut.mutate()}
                  disabled={resetMut.isPending}
                  className="text-rose-600 dark:text-rose-400"
                >
                  <RotateCcw className="h-3 w-3" /> {resetMut.isPending ? "恢复中…" : "恢复默认"}
                </Button>
                <Button size="sm" onClick={() => saveMut.mutate(draft)} disabled={saveMut.isPending}>
                  <Save className="h-3 w-3" /> {saveMut.isPending ? "保存中…" : "保存"}
                </Button>
              </div>
            </div>
            {saveMut.isError && (
              <p className="text-xs text-rose-600">保存失败:{(saveMut.error as ApiError).message}</p>
            )}
            {resetMut.isError && (
              <p className="text-xs text-rose-600">恢复失败:{(resetMut.error as ApiError).message}</p>
            )}
            {saveMut.isSuccess && (
              <p className="text-xs text-emerald-600">✓ 已保存到 persist/system_prompt.md,下次会话生效</p>
            )}
            {resetMut.isSuccess && (
              <p className="text-xs text-emerald-600">✓ 已删除覆写文件,回退默认静态版</p>
            )}
          </CardContent>
        </Card>
      ) : (
        <>
          {source === "override" && (
            <Badge variant="secondary" className="text-[10px]">会话级覆写中</Badge>
          )}
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
