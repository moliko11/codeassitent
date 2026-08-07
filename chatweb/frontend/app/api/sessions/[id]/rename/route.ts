// app/api/sessions/[id]/rename/route.ts - BFF:POST 转发重命名会话(Phase 1 §1.1)
// 后端更新 session 内存态 + run_meta 侧车;下次 list_runs / 历史恢复标题一致。
import { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const AGENT_API = process.env.AGENT_API || "http://localhost:8000";

export async function POST(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const body = await req.json();
  const r = await fetch(`${AGENT_API}/sessions/${id}/rename`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: body.title || "" }),
    signal: AbortSignal.timeout(10_000),
  });
  if (!r.ok) return new Response(await r.text(), { status: r.status });
  return Response.json(await r.json());
}
