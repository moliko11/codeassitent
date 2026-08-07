// app/api/sessions/[id]/messages/route.ts - BFF:GET 历史消息(读 transcript 转 ChatMessage)
// §1.5:读不到返回空(不阻断 UI)+ 10s 超时(后端挂时快速返回空而非挂死页面)。
import { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const AGENT_API = process.env.AGENT_API || "http://localhost:8000";

export async function GET(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  try {
    const r = await fetch(`${AGENT_API}/sessions/${id}/messages`, {
      signal: AbortSignal.timeout(10_000),
    });
    if (!r.ok) return Response.json([], { status: 200 }); // 读不到返回空(不阻断 UI)
    return Response.json(await r.json());
  } catch {
    return Response.json([], { status: 200 }); // 超时/网络断也返回空
  }
}
