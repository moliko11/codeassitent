// app/api/sessions/route.ts - BFF:GET 转发 list_runs()(喂 sidebar);POST 创建 session
import { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const AGENT_API = process.env.AGENT_API || "http://localhost:8000";

export async function GET() {
  const r = await fetch(`${AGENT_API}/sessions`);
  return Response.json(await r.json());
}

export async function POST(_req: NextRequest) {
  const r = await fetch(`${AGENT_API}/sessions`, { method: "POST" });
  return Response.json(await r.json());
}
