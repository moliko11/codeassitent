"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { ChatMessage, SessionSummary } from "@/lib/types";
import type { StreamEvent } from "@/lib/events";
import { applyEvent } from "@/lib/events";
import { readSSE } from "@/lib/sseStream";
import { newId } from "@/lib/mockData";

/**
 * ChatContext - 真实后端版(替换模板的 mock provider)。
 * 接 code/agent FastAPI 后端(经 Next.js BFF):POST /api/chat 流式消费 SSE,
 * eventReducer 聚合 12 事件 -> ChatMessage。sessions 来自 list_runs()。
 * 见 chat-template-integration.md §5/§7。
 */

// Sidebar 需要的形状(id/title/updatedAt);从后端 run_meta 转换
interface SidebarSession {
  id: string;
  title: string;
  updatedAt: number;
}

interface ChatContextValue {
  messages: ChatMessage[];
  isStreaming: boolean;
  sessions: SidebarSession[];
  activeSessionId: string | null;
  sendMessage: (content: string) => void;
  stopStreaming: () => void;
  newChat: () => void;
  selectSession: (id: string) => void;
}

const ChatContext = createContext<ChatContextValue | null>(null);

function toSidebarSession(r: SessionSummary): SidebarSession {
  return {
    id: r.run_id,
    title: r.model ? r.model.split("/").pop() || "对话" : "对话",
    updatedAt: (r.ended_at || r.started_at || 0) * 1000, // 后端是秒,前端用毫秒
  };
}

export function ChatProvider({ children }: { children: ReactNode }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [sessions, setSessions] = useState<SidebarSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const refreshSessions = useCallback(async () => {
    try {
      const r = await fetch("/api/sessions");
      const data: SessionSummary[] = await r.json();
      setSessions(data.map(toSidebarSession));
    } catch {
      /* 后端未起时静默 */
    }
  }, []);

  useEffect(() => {
    refreshSessions();
  }, [refreshSessions]);

  const stopStreaming = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setIsStreaming(false);
    setMessages((prev) =>
      prev.map((m) => (m.streaming ? { ...m, streaming: false, status: "failed" as const } : m)),
    );
  }, []);

  const sendMessage = useCallback(
    async (content: string) => {
      const text = content.trim();
      if (!text || isStreaming) return;

      const userMsg: ChatMessage = {
        id: newId("u"),
        role: "user",
        content: text,
        createdAt: Date.now(),
      };
      const assistantId = newId("a");
      const assistantMsg: ChatMessage = {
        id: assistantId,
        role: "assistant",
        content: "",
        streaming: true,
        toolCalls: [],
        createdAt: Date.now(),
      };
      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      setIsStreaming(true);

      // 首次发消息:建 session(= 新 run_id)
      let sid = activeSessionId;
      if (!sid) {
        try {
          const r = await fetch("/api/sessions", { method: "POST" });
          const { run_id } = await r.json();
          sid = run_id;
          setActiveSessionId(sid);
        } catch (e) {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? { ...m, streaming: false, status: "failed", content: `创建 session 失败: ${e}` }
                : m,
            ),
          );
          setIsStreaming(false);
          return;
        }
      }

      // 流式消费 SSE
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      try {
        let res = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ sessionId: sid, input: text }),
          signal: ctrl.signal,
        });
        // session 丢失(后端重启后内存 session_manager 清空)-> 重建 session 重试一次
        if (!res.ok && res.status === 404) {
          const r2 = await fetch("/api/sessions", { method: "POST" });
          const j2 = await r2.json();
          sid = j2.run_id;
          setActiveSessionId(sid);
          res = await fetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ sessionId: sid, input: text }),
            signal: ctrl.signal,
          });
        }
        if (!res.ok) throw new Error(await res.text());
        for await (const ev of readSSE(res)) {
          const typed = ev as unknown as StreamEvent;
          setMessages((prev) =>
            prev.map((m) => (m.id === assistantId ? applyEvent(m, typed) : m)),
          );
        }
      } catch (e: unknown) {
        const err = e as { name?: string; message?: string };
        if (err.name !== "AbortError") {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? { ...m, streaming: false, status: "failed", content: m.content || `错误: ${err.message || e}` }
                : m,
            ),
          );
        }
      } finally {
        abortRef.current = null;
        setIsStreaming(false);
        refreshSessions(); // 刷新 sidebar(新 run_meta)
      }
    },
    [isStreaming, activeSessionId, refreshSessions],
  );

  const newChat = useCallback(() => {
    stopStreaming();
    setMessages([]);
    setActiveSessionId(null);
  }, [stopStreaming]);

  const selectSession = useCallback(
    async (id: string) => {
      stopStreaming();
      setActiveSessionId(id);
      // 恢复历史消息:读 transcript 转 ChatMessage(后端 /sessions/:id/messages)
      try {
        const r = await fetch(`/api/sessions/${id}/messages`);
        if (!r.ok) throw new Error(await r.text());
        const msgs = await r.json();
        setMessages(msgs);
      } catch {
        setMessages([]);
      }
    },
    [stopStreaming],
  );

  return (
    <ChatContext.Provider
      value={{ messages, isStreaming, sessions, activeSessionId, sendMessage, stopStreaming, newChat, selectSession }}
    >
      {children}
    </ChatContext.Provider>
  );
}

export function useChat(): ChatContextValue {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error("useChat must be used within ChatProvider");
  return ctx;
}
