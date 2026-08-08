// 后端直连 API(Phase 2 §2.2,免 BFF)。web/桌面同用一份。
// 背景:静态导出后没有 Next.js BFF 层,前端直接 fetch http://localhost:8000(chatweb 后端,
// CORS 已 allow_origins=["*"])。AGENT_API 由 NEXT_PUBLIC_AGENT_API 构建期内联,默认 8000。
// 全部返回原始 Response:调用方按需 .json()/.ok(与旧 BFF 时代的错误处理保持一致)。
export const AGENT_API =
  (process.env.NEXT_PUBLIC_AGENT_API as string | undefined)?.replace(/\/$/, "") ||
  "http://localhost:8000";

export const apiSessions = () => fetch(`${AGENT_API}/sessions`);

export const apiCreateSession = () => fetch(`${AGENT_API}/sessions`, { method: "POST" });

export const apiApprove = (requestId: string, allow: boolean, reason = "") =>
  fetch(`${AGENT_API}/approve/${requestId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ allow, reason }),
  });

// 流式 turn:POST /sessions/:id/turn,返回 SSE 流(body 与 BFF 时代不同——后端只收 {input},
// sessionId 在 URL 路径里,原 BFF /api/chat 的 {sessionId, input} 在此解包)。
export const apiChat = (sessionId: string, input: string, signal: AbortSignal) =>
  fetch(`${AGENT_API}/sessions/${sessionId}/turn`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ input }),
    signal,
  });

export const apiMessages = (sessionId: string) =>
  fetch(`${AGENT_API}/sessions/${sessionId}/messages`);

// 后台自动 turn 事件长轮询(待办 A):GET /sessions/:id/events?timeout=20
// 后台 subagent 完成 -> 后端 session loop 自动起一轮 turn,事件缓冲;前端空闲时 long-poll 拉取。
export const apiEvents = (sessionId: string, signal?: AbortSignal) =>
  fetch(`${AGENT_API}/sessions/${sessionId}/events?timeout=20`, { signal });

export const apiRename = (sessionId: string, title: string) =>
  fetch(`${AGENT_API}/sessions/${sessionId}/rename`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });

// ── Phase 2 §2.5:桌面 diff 视图(文件版本链 + 内容)──

/** 该 run 编辑过的文件列表(喂 diff 面板左列)。 */
export const apiFiles = (runId: string) =>
  fetch(`${AGENT_API}/sessions/${runId}/files`);

/** 单文件版本链(key = sha256(abs_path)[:16],后端生成)。 */
export const apiFileVersions = (runId: string, key: string) =>
  fetch(`${AGENT_API}/sessions/${runId}/files/${key}/versions`);

/** 某版本内容:version 传 "current"(默认)读磁盘当前内容,传数字读该版本备份。 */
export const apiFileContent = (runId: string, key: string, version: number | "current" = "current") =>
  fetch(`${AGENT_API}/sessions/${runId}/files/${key}/content?version=${version}`);
