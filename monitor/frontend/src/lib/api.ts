// API 封装:fetch /api/*,走 Vite proxy 同源(免 CORS)。错误用具名 ApiError 抛出(组件 catch 显示空态)。
import type {
  AggregateStats,
  RunMeta,
  RunDetail,
  Trace,
  TranscriptRecord,
  SystemPrompt,
  Feedback,
} from "./types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

async function fetchJson<T>(path: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path);
  } catch {
    throw new ApiError(0, "网络错误:无法连接后端(确认 :8000 已启动)");
  }
  if (!res.ok) {
    let msg = `${path} -> ${res.status}`;
    try {
      const t = await res.text();
      if (t) msg = t;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, msg);
  }
  return (await res.json()) as T;
}

export const api = {
  stats: () => fetchJson<AggregateStats>("/api/stats"),
  runs: () => fetchJson<RunMeta[]>("/api/runs"),
  run: (id: string) => fetchJson<RunDetail>(`/api/runs/${encodeURIComponent(id)}`),
  trace: (id: string) => fetchJson<Trace>(`/api/runs/${encodeURIComponent(id)}/trace`),
  transcript: (id: string, limit = 100000) =>
    fetchJson<TranscriptRecord[]>(
      `/api/runs/${encodeURIComponent(id)}/transcript?limit=${limit}`,
    ),
  feedback: () => fetchJson<Feedback>("/api/feedback"),
  systemPrompt: () => fetchJson<SystemPrompt>("/api/system_prompt"),
};
