// react-query hooks:只读 API,缓存 + loading。4xx(无 trace 等)不重试。
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";

/** 4xx 不重试(无 trace/404 是正常情况);5xx/网络错误重试 2 次 */
const retryIfTransient = (count: number, err: unknown): boolean => {
  if (err instanceof ApiError && err.status >= 400 && err.status < 500) return false;
  return count < 2;
};

// Phase 3 §3.4:实时更新用 refetchInterval 轮询(plan 允许「refetchInterval 或 WS」)。
// 列表/聚合页 15s 自动刷新,新 run 完成约 15s 内出现在列表。详情页保持 staleTime(不轮询)。
const POLL_MS = 15_000;

export const useStats = () =>
  useQuery({
    queryKey: ["stats"],
    queryFn: api.stats,
    staleTime: 10_000,
    refetchInterval: POLL_MS,
    retry: retryIfTransient,
  });

export const useRuns = () =>
  useQuery({
    queryKey: ["runs"],
    queryFn: api.runs,
    staleTime: 10_000,
    refetchInterval: POLL_MS,
    retry: retryIfTransient,
  });

export const useRun = (id: string) =>
  useQuery({
    queryKey: ["run", id],
    queryFn: () => api.run(id),
    staleTime: 60_000,
    enabled: !!id,
    retry: retryIfTransient,
  });

export const useTrace = (id: string) =>
  useQuery({
    queryKey: ["trace", id],
    queryFn: () => api.trace(id),
    staleTime: 60_000,
    enabled: !!id,
    retry: retryIfTransient,
  });

export const useTranscript = (id: string) =>
  useQuery({
    queryKey: ["transcript", id],
    queryFn: () => api.transcript(id),
    staleTime: 60_000,
    enabled: !!id,
    retry: retryIfTransient,
  });

export const useSystemPrompt = () =>
  useQuery({
    queryKey: ["systemPrompt"],
    queryFn: api.systemPrompt,
    staleTime: Infinity,
    retry: retryIfTransient,
  });

export const useFeedback = () =>
  useQuery({
    queryKey: ["feedback"],
    queryFn: api.feedback,
    staleTime: 30_000,
    retry: retryIfTransient,
  });

// ── Phase 3 §3.2/§3.3/§3.5 ──

export const useSubagents = (id: string) =>
  useQuery({
    queryKey: ["subagents", id],
    queryFn: () => api.subagents(id),
    staleTime: 60_000,
    enabled: !!id,
    retry: retryIfTransient,
  });

export const useTools = () =>
  useQuery({
    queryKey: ["tools"],
    queryFn: api.tools,
    staleTime: 30_000,
    refetchInterval: POLL_MS,
    retry: retryIfTransient,
  });

export const useSaveSystemPrompt = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (raw: string) => api.saveSystemPrompt(raw),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["systemPrompt"] }),
  });
};

export const useResetSystemPrompt = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.resetSystemPrompt(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["systemPrompt"] }),
  });
};
