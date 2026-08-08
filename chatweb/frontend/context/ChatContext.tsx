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
import { eventReducer } from "@/lib/events";
import { newId } from "@/lib/mockData";
import { apiSessions, apiCreateSession, apiApprove, apiChat, apiMessages, apiRename, apiStreamUrl } from "@/lib/api";

/**
 * ChatContext - 真实后端版(替换模板的 mock provider)。
 * 接 code/agent FastAPI 后端(Phase 2 §2.2 起直连,静态导出后无 BFF 层)。
 * 单通道事件流:POST /sessions/:id/turn 只触发 turn;全部事件(用户 turn/自动 turn/HITL)
 * 经 GET /sessions/:id/stream 的常驻 SSE(EventSource)到达,eventReducer 聚合消息级事件
 * (AssistantMessage/ToolResultMessage/RunStart/RunEnd/ToolStart/ApprovalRequestEvent) -> ChatMessage。
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
  const approvalTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const streamRef = useRef<EventSource | null>(null);   // 会话事件流(单通道)
  const processedApprovalIdsRef = useRef<Set<string>>(new Set());   // 已处理过的 HITL 请求(防重连补发重复弹窗)

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
    // 关掉事件流(服务端 turn 照跑,事件在队列缓冲;重开会话/重连再同步)。
    streamRef.current?.close();
    streamRef.current = null;
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

  // HITL 弹窗处理:单通道下所有审批事件经 /stream 到达(restore 重放与重连补发会重叠,
  // 用 processedApprovalIds 去重——已处理过的请求不再弹窗)。
  const handleApprovalEvent = useCallback(
    (ev: Extract<StreamEvent, { type: "ApprovalRequestEvent" }>) => {
      if (processedApprovalIdsRef.current.has(ev.request_id)) return;
      processedApprovalIdsRef.current.add(ev.request_id);
      const req: ApprovalRequest = {
        requestId: ev.request_id,
        toolName: ev.tool_name,
        reason: ev.reason,
        arguments: ev.arguments,
      };
      // Phase 2 §2.6:桌面端走原生系统弹窗(主进程 dialog.showMessageBox,同步等结果),
      // web 浏览器走内嵌 modal。两种情况最终都 resolveApproval -> POST /approve 解后端 future。
      if (window.electronAPI?.askApproval) {
        void window.electronAPI
          .askApproval(req)
          .then((d) => resolveApproval(req.requestId, d.allow, d.reason))
          .catch(() => resolveApproval(req.requestId, false, "原生弹窗异常,自动拒绝"));
      } else {
        queueApproval(req);
      }
    },
    [queueApproval, resolveApproval],
  );

  // ── 会话事件流(单通道):一条 EventSource 订阅全部事件(用户/自动 turn + HITL) ──
  const closeStream = useCallback(() => {
    streamRef.current?.close();
    streamRef.current = null;
  }, []);

  const openStream = useCallback(
    (id: string) => {
      closeStream();
      const es = new EventSource(apiStreamUrl(id));
      es.onmessage = (e) => {
        try {
          const ev = JSON.parse(e.data) as StreamEvent;
          if (ev.type === "ApprovalRequestEvent") {
            handleApprovalEvent(ev);
          } else {
            setMessages((prev) => eventReducer({ messages: prev, streaming: true }, ev).messages);
            // RunStart/RunEnd 驱动 UI streaming 状态(POST /turn 只触发,不再流回)
            if (ev.type === "RunStart") setIsStreaming(true);
            else if (ev.type === "RunEnd") setIsStreaming(false);
          }
        } catch {
          /* 损坏行忽略 */
        }
      };
      es.onerror = () => setIsStreaming(false);   // 流断开保守压掉 streaming(EventSource 自动重连,断期间事件在服务端队列缓冲)
      streamRef.current = es;
    },
    [closeStream, handleApprovalEvent],
  );

  useEffect(() => () => closeStream(), [closeStream]);   // 卸载时关流

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
      setMessages((prev) => [...prev, userMsg]);
      setIsStreaming(true);

      // 首次发消息:建 session(= 新 run_id)。|| "" 让 sid 恒为 string(空串 falsy,照走 if 建号分支)。
      let sid = activeSessionId || "";
      if (!sid) {
        try {
          const r = await apiCreateSession();
          const { run_id } = await r.json();
          sid = run_id;
          setActiveSessionId(sid);
          openStream(sid);   // 新会话开流;turn 事件进队列,流连接后补发
        } catch (e) {
          setMessages((prev) => [
            ...prev,
            { id: newId("a"), role: "assistant", content: `创建 session 失败: ${e}`, streaming: false, status: "failed", createdAt: Date.now() },
          ]);
          setIsStreaming(false);
          return;
        }
      }

      // 流没开就重开(stopStreaming 关流后,用户再发消息仍能收到事件)
      if (!streamRef.current) openStream(sid);

      try {
        let res = await apiChat(sid, text);
        // session 丢失(后端重启后内存 session_manager 清空)-> 重建 session 重试一次
        if (!res.ok && res.status === 404) {
          const r2 = await apiCreateSession();
          const j2 = await r2.json();
          sid = j2.run_id;
          setActiveSessionId(sid);
          openStream(sid);
          res = await apiChat(sid, text);
        }
        if (!res.ok) throw new Error(await res.text());
        // 触发成功:事件经 /stream 到达,RunStart/RunEnd 驱动 streaming 状态;
        // 本 POST 只触发 turn,不读响应流。
      } catch (e: unknown) {
        const err = e as { name?: string; message?: string };
        setMessages((prev) => {
          // 有进行中的 assistant 消息 -> 标 failed;否则 append 一条错误气泡
          const streamingIdx = prev.findLastIndex((m) => m.streaming);
          if (streamingIdx >= 0) {
            return prev.map((m, i) =>
              i === streamingIdx
                ? { ...m, streaming: false, status: "failed" as const, content: m.content || `错误: ${err.message || e}` }
                : m,
            );
          }
          return [
            ...prev,
            { id: newId("a"), role: "assistant" as const, content: `错误: ${err.message || e}`, streaming: false, status: "failed" as const, createdAt: Date.now() },
          ];
        });
        setIsStreaming(false);
      } finally {
        refreshSessions(); // 刷新 sidebar(新 run_meta;RunEnd 已由 run_turn 落盘)
      }
    },
    [isStreaming, activeSessionId, refreshSessions, openStream],
  );

  const newChat = useCallback(() => {
    stopStreaming();
    closeStream();
    setMessages([]);
    setActiveSessionId(null);
  }, [stopStreaming, closeStream]);

  const selectSession = useCallback(
    async (id: string) => {
      stopStreaming();
      closeStream();
      setActiveSessionId(id);
      // 恢复历史消息:优先重放 events.jsonl(后端 /sessions/:id/messages source=events),
      // 恢复画面 = 直播画面(eventReducer 是唯一投影,前端不维护第二套恢复逻辑);
      // 老 run(无 events.jsonl)退化用后端 transcript 转好的 ChatMessage(source=transcript)。
      try {
        const r = await apiMessages(id);
        if (!r.ok) throw new Error(await r.text());
        const data = await r.json();
        if (data?.source === "events") {
          let st: { messages: ChatMessage[]; streaming: boolean } = { messages: [], streaming: false };
          for (const ev of (data.events as StreamEvent[]) || []) {
            st = eventReducer(st, ev);
          }
          // 无 RunEnd 的 run(中断)reducer 停在 streaming:true,恢复时压成 completed 快照,
          // 避免恢复出来的历史一直转圈(与 transcript 路径的 completed 默认对齐)。
          setMessages(
            st.streaming
              ? st.messages.map((m) => ({ ...m, streaming: false, status: "completed" as const }))
              : st.messages,
          );
        } else {
          setMessages((data?.messages as ChatMessage[]) || []);
        }
      } catch {
        setMessages([]);
      }
      // 恢复后开流:新事件(用户/自动 turn + HITL)从这来。断期间事件在服务端队列缓冲,
      // 重连补发;与 restore 重叠的事件由 eventReducer 按 uuid 幂等去重。
      openStream(id);
    },
    [stopStreaming, closeStream, openStream],
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
