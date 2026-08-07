// app/api/chat/route.ts - BFF:转发到 Python POST /sessions/:id/turn,透传 SSE 流
// 同源(前端 :3000 -> BFF -> Python :8000),免 CORS;上云时前端(Vercel)与 Python(Docker)分离。
import { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const AGENT_API = process.env.AGENT_API || "http://localhost:8000";

export async function POST(req: NextRequest) {
  const { sessionId, input } = await req.json();
  const upstream = await fetch(`${AGENT_API}/sessions/${sessionId}/turn`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ input }),
  });
  if (!upstream.ok) {
    return new Response(await upstream.text(), { status: upstream.status });
  }
  const body = upstream.body;
  if (!body) {
    return new Response("upstream empty body", { status: 502 });
  }
  // 显式 ReadableStream pipe,避免 Next.js dev buffer 整个 SSE 响应
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      const reader = body.getReader();
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          controller.enqueue(value);
        }
      } catch (e) {
        controller.error(e);
      } finally {
        controller.close();
      }
    },
  });
  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      "Connection": "keep-alive",
    },
  });
}
