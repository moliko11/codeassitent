// app/api/sessions/[id]/route.ts - BFF:GET 单 run 指标(read_run_report)
import { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const AGENT_API = process.env.AGENT_API || "http://localhost:8000";

export async function GET(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const r = await fetch(`${AGENT_API}/sessions/${id}`, {
    signal: AbortSignal.timeout(10_000),
  });
  if (!r.ok) return Response.json({ error: "not found" }, { status: 404 });
  return Response.json(await r.json());
}
