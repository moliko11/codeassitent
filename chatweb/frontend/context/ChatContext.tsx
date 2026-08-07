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
import type { ApprovalRequest, ChatMessage, SessionSummary } from "@/lib/types";
import type { StreamEvent } from "@/lib/events";
import { applyEvent } from "@/lib/events";
import { readSSE } from "@/lib/sseStream";
import { newId } from "@/lib/mockData";
import { apiSessions, apiCreateSession, apiApprove, apiChat, apiMessages, apiRename } from "@/lib/api";

/**
 * ChatContext - 真实后端版(替换模板的 mock provider)。
 * 接 code/agent FastAPI 后端(Phase 2 §2.2 起直连,静态导出后无 BFF 层):
 * POST /sessions/:id/turn 流式消费 SSE,eventReducer 聚合 12 事件 -> ChatMessage。
 * sessions 来自 list_runs()。见 chat-template-integration.md §5/§7。
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
  renameSession: (title: string) => Promise<void>;
  pendingApproval: ApprovalRequest | null;
  resolveApproval: (requestId: string, allow: boolean, reason?: string) => void;
}

const ChatContext = createContext<ChatContextValue | null>(null);

function toSidebarSession(r: SessionSummary): SidebarSession {
  // Phase 1 §1.1:标题优先取 run_meta 的 title(首条 user 推导/用户重命名),没有才退化 model 名
  const title =
    (r.title && r.title.trim()) ||
    (r.model ? r.model.split("/").pop() || "" : "") ||
    "对话";
  return {
    id: r.run_id,
    title,
    updatedAt: (r.ended_at || r.started_at || 0) * 1000, // 后端是秒,前端用毫秒
  };
}

const APPROVAL_TIMEOUT_MS = 60_000; // 弹窗无响应自动拒绝(plan §0.7 临时方案:SSE 断连防永久挂起)

export function ChatProvider({ children }: { children: ReactNode }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [sessions, setSessions] = useState<SidebarSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [pendingApproval, setPendingApproval] = useState<ApprovalRequest | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const approvalTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refreshSessions = useCallback(async () => {
    try {
      const r = await apiSessions();
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

  // 用户点弹窗的 Allow/Deny -> POST /approve/{id} 解后端 future(或超时自动拒绝)
  const resolveApproval = useCallback(
    async (requestId: string, allow: boolean, reason?: string) => {
      if (approvalTimerRef.current) {
        clearTimeout(approvalTimerRef.current);
        approvalTimerRef.current = null;
      }
      setPendingApproval(null);
      try {
        await apiApprove(requestId, allow, reason || "");
      } catch {
        /* 后端未起/网络断:静默,SSE 断开会让工具在服务端超时自动拒绝 */
      }
    },
    [],
  );

  const queueApproval = useCallback(
    (req: ApprovalRequest) => {
      setPendingApproval(req);
      // 60s 无响应自动拒绝(front-end timeout,plan §0.7;后端还有 300s 兜底)
      if (approvalTimerRef.current) clearTimeout(approvalTimerRef.current);
      approvalTimerRef.current = setTimeout(() => {
        approvalTimerRef.current = null;
        setPendingApproval(null);
        void resolveApproval(req.requestId, false, "审批超时,自动拒绝");
      }, APPROVAL_TIMEOUT_MS);
    },
    [resolveApproval],
  );

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

      // 首次发消息:建 session(= 新 run_id)。|| "" 让 sid 恒为 string(空串 falsy,照走 if 建号分支)。
      let sid = activeSessionId || "";
      if (!sid) {
        try {
          const r = await apiCreateSession();
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
        let res = await apiChat(sid, text, ctrl.signal);
        // session 丢失(后端重启后内存 session_manager 清空)-> 重建 session 重试一次
        if (!res.ok && res.status === 404) {
          const r2 = await apiCreateSession();
          const j2 = await r2.json();
          sid = j2.run_id;
          setActiveSessionId(sid);
          res = await apiChat(sid, text, ctrl.signal);
        }
        if (!res.ok) throw new Error(await res.text());
        for await (const ev of readSSE(res)) {
          const typed = ev as unknown as StreamEvent;
          // HITL(阶段0):需人工批准 -> 弹窗(不进消息体);点 Allow/Deny 后 POST /approve 解 future
          if (typed.type === "ApprovalRequestEvent") {
            queueApproval({
              requestId: typed.request_id,
              toolName: typed.tool_name,
              reason: typed.reason,
              arguments: typed.arguments,
            });
            continue;
          }
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
    [isStreaming, activeSessionId, refreshSessions, queueApproval],
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
        const r = await apiMessages(id);
        if (!r.ok) throw new Error(await r.text());
        const msgs = await r.json();
        setMessages(msgs);
      } catch {
        setMessages([]);
      }
    },
    [stopStreaming],
  );

  // Phase 1 §1.1:重命名当前会话 -> POST BFF -> 后端更新 session 内存态 + run_meta 侧车,
  // 成功后刷新 sessions 让 sidebar 立即反映(标题下次 refreshSessions 也保持一致)。
  const renameSession = useCallback(
    async (title: string) => {
      const next = title.trim();
      if (!next || !activeSessionId) return;
      try {
        const r = await apiRename(activeSessionId, next);
        if (!r.ok) return;
      } catch {
        return; /* 后端未起:静默,只更新本地 */
      }
      setSessions((prev) =>
        prev.map((s) => (s.id === activeSessionId ? { ...s, title: next } : s)),
      );
    },
    [activeSessionId],
  );

  return (
    <ChatContext.Provider
      value={{ messages, isStreaming, sessions, activeSessionId, sendMessage, stopStreaming, newChat, selectSession, renameSession, pendingApproval, resolveApproval }}
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
