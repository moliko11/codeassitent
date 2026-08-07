// 后端 JSON 的 TS 类型(逐字对照实跑 curl 的返回,见 docs/monitor-frontend-design.md §0.2)
// 字段缺失一律兜底:消费方用 `?? 0 / ""`,类型上保留可选。

export interface RunMeta {
  run_id: string;
  status: string;
  started_at: number;       // 墙钟秒
  ended_at: number | null;
  duration_ms: number;
  token_input: number;
  token_output: number;
  token_total: number;
  token_cached: number;     // input 子集,命中率 = cached/input
  step_count: number;
  tool_count: number;
  tool_success_rate: number;
  model: string;
  system_prompt?: string;   // 列表项也带(前端列表不渲染),详情页分层展示
}

export interface RunReport {
  run_id: string;
  status: string;
  duration_ms: number;
  step_count: number;
  tool_count: number;
  tool_success_count: number;
  tool_success_rate: number;
  avg_tool_latency_ms: number;
  token_input: number;
  token_output: number;
  token_total: number;
  token_cached: number;
  timeout_count: number;
  retry_count: number;
}

export interface RunDetail {
  meta: RunMeta;
  report: RunReport | null; // trace 不存在(崩了没 RunEnd)则 null
}

export type SpanType = "run" | "step" | "tool" | "guardrail" | "approval";

export interface SpanUsage {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cached_tokens?: number;
}

export interface SpanAttrs {
  status?: string;          // run
  usage?: SpanUsage;        // step(LLM 返回的精确 token)
  ok?: boolean;             // tool
  error_type?: string;
  call_id?: string;
  agent_id?: string;        // 非空 = 子 agent(task 工具派的),火焰图标红边/[子]
  elapsed_ms?: number;
  attempts?: number;        // >1 = 有重试
  summary?: string;
}

export interface Span {
  span_id: string;
  parent_id: string | null; // null = 根(run)
  type: SpanType;
  name: string;
  start: number;            // perf_counter 相对值,非墙钟
  end: number;
  duration_ms: number;
  attrs: SpanAttrs;
}

export interface Trace {
  run_id: string;
  spans: Span[];
}

export interface ToolCall {
  call_id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  meta?: unknown;
  depends_on?: string | null; // 非空 = 有依赖走 DAG;空 = 同批并行
}

export interface ToolResult {
  call_id: string;
  tool_name: string;
  ok: boolean;
  data?: unknown;           // 可为 string / object / array
  error?: string | null;
  text?: string;
  meta?: unknown;
}

export type TranscriptType = "user" | "assistant" | "tool_result" | "run_end";

export interface TranscriptRecord {
  type: TranscriptType;
  run_id: string;
  ts: number;
  uuid?: string;
  content?: string;         // user
  text?: string;            // assistant
  tool_calls?: ToolCall[];  // assistant;同一条 >1 个 = 并行批次(execute_many 同轮并发)
  result?: ToolResult;      // tool_result
  status?: string;          // run_end(不一定存在)
  agent_id?: string | null; // 非空 = 子 agent 落主 transcript
}

export interface DayBucket { token: number; runs: number; }
export interface ModelBucket { token: number; runs: number; }

export interface AggregateStats {
  run_count: number;
  total_token_input: number;
  total_token_output: number;
  total_token: number;
  total_token_cached: number;
  avg_cache_hit_rate: number;
  avg_tool_success_rate: number;
  total_cost: number;       // 恒 0(TODO)
  by_day: Record<string, DayBucket>;   // {date: {token,runs}},含 "unknown" 桶
  by_model: Record<string, ModelBucket>;
}

export interface PromptSection { title: string; body: string; }
export interface SystemPrompt {
  intro: string;
  sections: PromptSection[];
  raw: string;
}

export type Feedback = Record<string, unknown>;
