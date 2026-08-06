// app/api/sessions/[id]/messages/route.ts - BFF:GET 历史消息(读 transcript 转 ChatMessage)
import { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const AGENT_API = process.env.AGENT_API || "http://localhost:8000";

export async function GET(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const r = await fetch(`${AGENT_API}/sessions/${id}/messages`);
  if (!r.ok) return Response.json([], { status: 200 }); // 读不到返回空(不阻断 UI)
  return Response.json(await r.json());
}
