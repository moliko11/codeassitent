// lib/events.ts - 后端 13 流式事件的 TS 类型 + reducer(对齐 events.py:107)
// 一个 turn 的事件流聚合成一条 ChatMessage。关联键 call_id:
// ToolCallStart/Delta/End(模型产参)与 ToolStart/End(执行器执行)按 call_id 聚合成一个 ToolCallView。
// ApprovalRequestEvent(HITL)不进消息体——ChatContext 捕获它弹 ApprovalDialog。
import type { ChatMessage, ToolCallView, TokenUsage } from "./types";

export type StreamEvent =
  | { type: "RunStart"; run_id: string }
  | { type: "StepStart"; step_index: number }
  | { type: "StepEnd"; step_index: number }
  | { type: "RunEnd"; status: string; final_text: string | null; error: Record<string, unknown> | null }
  | { type: "ToolStart"; call_id: string; tool_name: string; arguments: Record<string, unknown> }
  | { type: "ToolEnd"; call_id: string; tool_name: string; ok: boolean; elapsed_ms: number; error_type: string | null; summary: string | null; attempts: number }
  | { type: "ApprovalRequestEvent"; request_id: string; tool_name: string; reason: string; arguments: Record<string, unknown> }
  | { type: "TextDelta"; text: string }
  | { type: "ThinkingDelta"; text: string }
  | { type: "ToolCallStart"; call_id: string; tool_name: string; index: number }
  | { type: "ToolCallDelta"; call_id: string; arguments_delta: string }
  | { type: "ToolCallEnd"; call_id: string }
  | { type: "MessageEnd"; stop_reason: string | null; usage: TokenUsage | null };

function tryParse(s: string): object | undefined {
  try { return JSON.parse(s); } catch { return undefined; }
}

/** 把一个事件应用到 assistant 消息上,返回新消息(不可变更新)。 */
export function applyEvent(msg: ChatMessage, ev: StreamEvent): ChatMessage {
  switch (ev.type) {
    case "ThinkingDelta":
      return { ...msg, thinking: (msg.thinking || "") + ev.text };
    case "TextDelta":
      return { ...msg, content: msg.content + ev.text };
    case "ToolCallStart": {
      const tc: ToolCallView = { callId: ev.call_id, toolName: ev.tool_name, argumentsJson: "", phase: "producing" };
      return { ...msg, toolCalls: [...(msg.toolCalls || []), tc] };
    }
    case "ToolCallDelta":
      return { ...msg, toolCalls: (msg.toolCalls || []).map(tc => tc.callId === ev.call_id ? { ...tc, argumentsJson: tc.argumentsJson + ev.arguments_delta } : tc) };
    case "ToolCallEnd":
      return { ...msg, toolCalls: (msg.toolCalls || []).map(tc => tc.callId === ev.call_id ? { ...tc, arguments: tryParse(tc.argumentsJson) } : tc) };
    case "ToolStart":
      return { ...msg, toolCalls: (msg.toolCalls || []).map(tc => tc.callId === ev.call_id ? { ...tc, phase: "running" } : tc) };
    case "ToolEnd":
      // Phase 1 §1.3:失败时带 error_type(分类展示);历史恢复路径(_transcript_to_messages)从 transcript 的 error 取
      return { ...msg, toolCalls: (msg.toolCalls || []).map(tc => tc.callId === ev.call_id ? { ...tc, phase: ev.ok ? "done" : "error", ok: ev.ok, summary: ev.summary || undefined, elapsedMs: ev.elapsed_ms, attempts: ev.attempts, errorType: ev.ok ? undefined : (ev.error_type || undefined), errorMessage: ev.ok ? undefined : (ev.summary || undefined) } : tc) };
    case "MessageEnd":
      return { ...msg, usage: ev.usage || undefined };
    case "RunEnd":
      return { ...msg, streaming: false, status: ev.status === "completed" ? "completed" : "failed", content: msg.content || ev.final_text || "" };
    default:
      return msg; // RunStart / StepStart / StepEnd 不改消息体
  }
}
