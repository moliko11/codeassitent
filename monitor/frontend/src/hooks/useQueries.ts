// react-query hooks:只读 API,缓存 + loading。4xx(无 trace 等)不重试。
import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";

/** 4xx 不重试(无 trace/404 是正常情况);5xx/网络错误重试 2 次 */
const retryIfTransient = (count: number, err: unknown): boolean => {
  if (err instanceof ApiError && err.status >= 400 && err.status < 500) return false;
  return count < 2;
};

export const useStats = () =>
  useQuery({ queryKey: ["stats"], queryFn: api.stats, staleTime: 10_000, retry: retryIfTransient });

export const useRuns = () =>
  useQuery({ queryKey: ["runs"], queryFn: api.runs, staleTime: 10_000, retry: retryIfTransient });

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
