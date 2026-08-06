// lib/sseStream.ts - 从 fetch Response 的 ReadableStream 解析 SSE data 行
// 不用 EventSource(只 GET 传不了 input body);用 fetch POST + 流式消费(对齐 chat-template-integration §4)。

export async function* readSSE(res: Response): AsyncGenerator<Record<string, unknown>> {
  if (!res.body) return;
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      // SSE 事件以空行(\n\n)分隔
      let idx: number;
      while ((idx = buffer.indexOf("\n\n")) !== -1) {
        const chunk = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        for (const line of chunk.split("\n")) {
          if (line.startsWith("data: ")) {
            try { yield JSON.parse(line.slice(6)); } catch { /* 跳过损坏行 */ }
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
