// 本 run 实际注入的系统提示词(meta.system_prompt,动态版)分层 + 动态会话级段标记。
// 区别于 /prompt 页(静态默认版):此处含语言/环境/仓库/工具结果清理等动态段。
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/common/EmptyState";
import { splitSections } from "@/lib/format";
import { isDynamicSection } from "@/lib/constants";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function SystemPromptView({ prompt }: { prompt?: string }) {
  if (!prompt) return <EmptyState title="无系统提示词" desc="旧 run 无此字段" />;
  const { intro, sections } = splitSections(prompt);
  return (
    <div className="space-y-3">
      {intro && (
        <Card className="border-l-4 border-l-amber-400">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">引言</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="prose-sm">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{intro}</ReactMarkdown>
            </div>
          </CardContent>
        </Card>
      )}
      {sections.map((s, i) => (
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
    </div>
  );
}
