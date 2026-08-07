// app/api/sessions/route.ts - BFF:GET 转发 list_runs()(喂 sidebar);POST 创建 session
// §1.5:错误传播(透传上游 status,不让 Sidebar 静默吞 5xx)+ 非流式路由 10s 超时。
import { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const AGENT_API = process.env.AGENT_API || "http://localhost:8000";
const TIMEOUT_MS = 10_000; // 非流式路由:后端无响应时 BFF 快速 504,不挂死

export async function GET() {
  const r = await fetch(`${AGENT_API}/sessions`, { signal: AbortSignal.timeout(TIMEOUT_MS) });
  if (!r.ok) return new Response(await r.text(), { status: r.status });
  return Response.json(await r.json());
}

export async function POST(_req: NextRequest) {
  const r = await fetch(`${AGENT_API}/sessions`, {
    method: "POST",
    signal: AbortSignal.timeout(TIMEOUT_MS),
  });
  if (!r.ok) return new Response(await r.text(), { status: r.status });
  return Response.json(await r.json());
}
