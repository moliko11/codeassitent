// API 封装:fetch /api/*,走 Vite proxy 同源(免 CORS)。错误用具名 ApiError 抛出(组件 catch 显示空态)。
import type {
  AggregateStats,
  RunMeta,
  RunDetail,
  Trace,
  TranscriptRecord,
  SystemPrompt,
  Feedback,
  ToolStat,
  SubagentActivity,
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

/** 写操作(POST/DELETE):同 fetchJson 但带 method + JSON body。 */
async function fetchMutate<T>(path: string, method: "POST" | "DELETE", body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method,
      headers: body != null ? { "Content-Type": "application/json" } : undefined,
      body: body != null ? JSON.stringify(body) : undefined,
    });
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
  // Phase 3 §3.3:写系统提示词覆写(保存/恢复默认)
  saveSystemPrompt: (raw: string) =>
    fetchMutate<{ ok: boolean }>("/api/system_prompt", "POST", { raw }),
  resetSystemPrompt: () => fetchMutate<{ ok: boolean }>("/api/system_prompt", "DELETE"),
  // Phase 3 §3.2:子 agent 活动
  subagents: (id: string) =>
    fetchJson<SubagentActivity[]>(`/api/runs/${encodeURIComponent(id)}/subagents`),
  // Phase 3 §3.5:工具使用统计
  tools: () => fetchJson<ToolStat[]>("/api/stats/tools"),
};
