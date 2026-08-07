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
  argumentsJson: string; // ToolCallDelta 累积的原始 JSON 串
  arguments?: object;    // ToolCallEnd 后 parse
  phase: "producing" | "running" | "done" | "error"; // 产参 -> 执行 -> 完成
  ok?: boolean;
  summary?: string;      // ToolEnd.summary
  elapsedMs?: number;
  attempts?: number;     // ToolEnd.attempts(>1 表示重试过)
  errorType?: string;    // Phase 1 §1.3:失败分类(ToolExecutionError/GuardrailBlocked/SchemaValidationError…)
  errorMessage?: string; // Phase 1 §1.3:失败原因(历史恢复从 transcript error 拿,流式从 ToolEnd.error_type)
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;          // TextDelta 累积
  thinking?: string;        // ThinkingDelta 累积(折叠展示)
  toolCalls?: ToolCallView[];
  usage?: TokenUsage;       // MessageEnd.usage
  streaming?: boolean;
  status?: "running" | "completed" | "failed";
  createdAt: number;
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
