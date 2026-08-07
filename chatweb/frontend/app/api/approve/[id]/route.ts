// app/api/approve/[id]/route.ts - BFF:转发到 Python POST /approve/{id},解 HITL future
// 用户点弹窗 Allow/Deny -> 本路由 -> 后端 resolve_web_approval(request_id, decision)。
import { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const AGENT_API = process.env.AGENT_API || "http://localhost:8000";

export async function POST(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const body = await req.json();
  const r = await fetch(`${AGENT_API}/approve/${id}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ allow: !!body.allow, reason: body.reason || "" }),
  });
  if (!r.ok) return new Response(await r.text(), { status: r.status });
  return Response.json(await r.json());
}
