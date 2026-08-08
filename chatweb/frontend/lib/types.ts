// lib/types.ts - 前端数据模型(对齐后端 events.py / metrics.py / run_meta)
// 扩展自模板 mockData.ts 的扁平 ChatMessage,加 thinking/toolCalls/usage/status。

export interface TokenUsage {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cached_tokens?: number; // 缓存命中(命中率 = cached/input)
}

export interface ToolCallView {
  callId: string;
  toolName: string;
  argumentsJson: string; // 序列化后的参数 JSON(消息级事件已解析,无需累积)
  arguments?: object;    // 解析后的参数对象
  phase: "producing" | "running" | "done" | "error"; // 产参 -> 执行 -> 完成
  ok?: boolean;
  summary?: string;      // ToolResultMessage.summary
  elapsedMs?: number;    // ToolResultMessage.elapsed_ms(实测)
  attempts?: number;     // ToolResultMessage.attempts(>1 表示重试过)
  errorType?: string;    // Phase 1 §1.3:失败分类(ToolExecutionError/GuardrailBlocked/SchemaValidationError…)
  errorMessage?: string; // Phase 1 §1.3:失败原因(历史恢复从 transcript error 拿,流式从 ToolResultMessage)
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system"; // system = 系统提示行(后台任务完成通知等)
  content: string;          // AssistantMessage.text(整包,非累积)
  thinking?: string;        // AssistantMessage.thinking(整包,折叠展示)
  toolCalls?: ToolCallView[];
  usage?: TokenUsage;       // AssistantMessage.usage(每 step 独立,数据保留;展示不用)
  turnUsage?: TokenUsage;   // RunEnd 携带的整轮聚合(对齐 CC result.usage)——只在 turn 结束显示总账
  durationMs?: number;      // RunEnd.duration_ms(本轮耗时)
  numSteps?: number;        // RunEnd.num_steps(本轮步数,对齐 CC num_turns)
  streaming?: boolean;
  status?: "running" | "completed" | "failed";
  createdAt: number;
  // 内部:TextDelta 累加中的占位气泡标记(streaming 但尚未被 AssistantMessage 定稿)。
  // reducer 靠它把 delta 追加到正确气泡,并在 AssistantMessage 到达时替换而非新建。
  _deltaStreaming?: boolean;
}

// HITL 批准请求(后端 ApprovalRequestEvent 对齐)
export interface ApprovalRequest {
  requestId: string;
  toolName: string;
  reason: string;
  arguments: Record<string, unknown>;
}

// list_runs() 返回的 run_meta 摘要(对齐 _write_run_meta 字段)
export interface SessionSummary {
  run_id: string;
  title?: string;        // Phase 1 §1.1:会话标题(首条 user 推导/前端重命名,落 run_meta)
  status?: string;
  started_at?: number;
  ended_at?: number;
  duration_ms?: number;
  token_total?: number;
  token_input?: number;
  token_output?: number;
  token_cached?: number;
  step_count?: number;
  tool_count?: number;
  tool_success_rate?: number;
  model?: string;
}
