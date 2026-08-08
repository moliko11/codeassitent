// lib/events.ts - web 消费的消息级事件(对齐后端 events.py 消息级契约 + CC 外部 StructuredIO)
// 后端 server.py _is_web_event 白名单只转发 6 种自包含事件,前端不用再累积 delta:
//   RunStart / RunEnd          - turn 书签
//   AssistantMessage           - 完整 assistant 消息(每 step 一条,自带 usage/tool_calls)
//   ToolStart                  - 工具开始(resume/_workflow 无 LLM step 时给前端建卡)
//   ToolResultMessage          - 完整工具结果(call_id 关联,自带 elapsed_ms)
//   ApprovalRequestEvent       - HITL(ChatContext 拦截弹窗,不进消息体)
// 关联键 call_id:AssistantMessage.tool_calls 建卡,ToolResultMessage 按 call_id 跨消息 patch。
import type { ChatMessage, ToolCallView, TokenUsage } from "./types";

export type StreamEvent =
  | { type: "RunStart"; run_id: string }
  | {
      type: "RunEnd";
      status: string;
      final_text: string | null;
      error: Record<string, unknown> | null;
      usage: TokenUsage | null; // 整轮聚合(对齐 CC result.usage;turn 结束才显示总账)
      duration_ms: number | null;
      num_steps: number | null;
    }
  | {
      type: "AssistantMessage";
      run_id: string;
      uuid: string;
      agent_id: string | null;
      step_index: number | null;
      text: string;
      thinking: string;
      tool_calls: { call_id: string; tool_name: string; arguments: Record<string, unknown> }[];
      stop_reason: string | null;
      usage: TokenUsage | null;
    }
  | { type: "ToolStart"; call_id: string; tool_name: string; arguments: Record<string, unknown> }
  | {
      type: "ToolResultMessage";
      run_id: string;
      uuid: string;
      call_id: string;
      tool_name: string;
      ok: boolean;
      summary: string | null;
      elapsed_ms: number;
      attempts: number;
      error_type: string | null;
      agent_id: string | null;
    }
  | { type: "ApprovalRequestEvent"; request_id: string; tool_name: string; reason: string; arguments: Record<string, unknown> };

export interface ChatState {
  messages: ChatMessage[];
  streaming: boolean;
}

function toolCallView(tc: {
  call_id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
}): ToolCallView {
  const args = tc.arguments ?? {};
  return {
    callId: tc.call_id,
    toolName: tc.tool_name,
    argumentsJson: JSON.stringify(args),
    arguments: args,
    phase: "producing",
  };
}

/** 按 call_id 找跨消息的 ToolCallView,返回 (messageIdx, toolIdx);找不到返回 null。 */
function findToolCall(msgs: ChatMessage[], callId: string): { m: number; t: number } | null {
  for (let m = 0; m < msgs.length; m++) {
    const tcs = msgs[m].toolCalls || [];
    for (let t = 0; t < tcs.length; t++) {
      if (tcs[t].callId === callId) return { m, t };
    }
  }
  return null;
}

function patchToolCall(
  msgs: ChatMessage[],
  callId: string,
  patch: Partial<ToolCallView>,
): ChatMessage[] {
  const found = findToolCall(msgs, callId);
  if (!found) return msgs;
  const { m, t } = found;
  return msgs.map((msg, i) =>
    i !== m
      ? msg
      : { ...msg, toolCalls: (msg.toolCalls || []).map((tc, j) => (j === t ? { ...tc, ...patch } : tc)) },
  );
}

export function initialState(): ChatState {
  return { messages: [], streaming: false };
}

/** 有状态 reducer:输入一个消息级事件,产出新的消息列表(每 step 独立气泡 + 按 call_id 关联)。 */
export function eventReducer(state: ChatState, ev: StreamEvent): ChatState {
  switch (ev.type) {
    case "RunStart":
      return { ...state, streaming: true };

    case "AssistantMessage": {
      // 每 step 一条消息,自带 usage(修"只显示最后一步 token")
      const msg: ChatMessage = {
        id: ev.uuid,
        role: "assistant",
        content: ev.text,
        thinking: ev.thinking || undefined,
        toolCalls: ev.tool_calls.map(toolCallView),
        usage: ev.usage || undefined,
        streaming: true,
        createdAt: Date.now(),
      };
      return { ...state, messages: [...state.messages, msg], streaming: true };
    }

    case "ToolStart": {
      // 正常路径:AssistantMessage.tool_calls 已建卡,这里仅置 running。
      // resume/_workflow 无 LLM step:没有卡,用 ToolStart 建卡(参数来自 ToolStart.arguments)。
      const found = findToolCall(state.messages, ev.call_id);
      if (found) return { ...state, messages: patchToolCall(state.messages, ev.call_id, { phase: "running" }) };
      const tc: ToolCallView = {
        callId: ev.call_id,
        toolName: ev.tool_name,
        argumentsJson: JSON.stringify(ev.arguments ?? {}),
        arguments: ev.arguments ?? {},
        phase: "running",
      };
      const msgs = [...state.messages];
      const last = msgs[msgs.length - 1];
      if (last && last.role === "assistant") {
        return { ...state, messages: [...msgs.slice(0, -1), { ...last, toolCalls: [...(last.toolCalls || []), tc] }] };
      }
      return {
        ...state,
        messages: [...msgs, { id: "ph-" + ev.call_id, role: "assistant", content: "", toolCalls: [tc], streaming: true, createdAt: Date.now() }],
      };
    }

    case "ToolResultMessage": {
      const msgs = state.messages;
      if (!findToolCall(msgs, ev.call_id)) {
        // 兜底:结果到了但卡没了,append 一张已完成卡(不丢结果)
        const tc: ToolCallView = {
          callId: ev.call_id,
          toolName: ev.tool_name,
          argumentsJson: "{}",
          arguments: {},
          phase: ev.ok ? "done" : "error",
          ok: ev.ok,
          summary: ev.summary || undefined,
          elapsedMs: ev.elapsed_ms,
          attempts: ev.attempts,
          errorType: ev.ok ? undefined : ev.error_type || undefined,
          errorMessage: ev.ok ? undefined : ev.summary || undefined,
        };
        return {
          ...state,
          messages: [...msgs, { id: "res-" + ev.call_id, role: "assistant", content: "", toolCalls: [tc], streaming: false, createdAt: Date.now() }],
        };
      }
      return {
        ...state,
        messages: patchToolCall(msgs, ev.call_id, {
          phase: ev.ok ? "done" : "error",
          ok: ev.ok,
          summary: ev.summary || undefined,
          elapsedMs: ev.elapsed_ms, // 修"始终 0ms"(ToolResultMessage.elapsed_ms 实测值)
          attempts: ev.attempts,
          errorType: ev.ok ? undefined : ev.error_type || undefined,
          errorMessage: ev.ok ? undefined : ev.summary || undefined,
        }),
      };
    }

    case "RunEnd": {
      const finalText = ev.final_text || "";
      return {
        ...state,
        streaming: false,
        messages: state.messages.map((m, i) => {
          if (m.role !== "assistant") return m;
          const isLast = i === state.messages.length - 1;
          return {
            ...m,
            streaming: false,
            status: ev.status === "completed" ? "completed" : "failed",
            // 最后一条无文本(纯工具轮)时用 final_text 兜底
            content: m.content || (isLast ? finalText : ""),
            // 整轮总账挂最后一条 assistant(对齐 CC result:turn 结束才报 token 总统计)
            ...(isLast && ev.usage
              ? {
                  turnUsage: ev.usage,
                  durationMs: ev.duration_ms ?? undefined,
                  numSteps: ev.num_steps ?? undefined,
                }
              : {}),
          };
        }),
      };
    }

    default:
      return state;
  }
}
