# ez-interview-agent

面试学习用 **Agent Runtime** —— 参照 Claude Code 的工程实践,按 11 个阶段逐阶段手写实现的 Agent 运行时。从最底层 `core/` 纯数据层起步,一路做到:主循环 / 工具系统 / 上下文压缩 / 长期记忆 / 安全护栏 / 可靠性 / Tracing / 多 Agent / 三端(CLI·web·desktop)。阶段 0~10 已完成,阶段 11(系统设计整合)待开始。

每个阶段 = 一个面试章节 + 代码任务 + 验收标准,路线图见 `docs/stages/agent-dev-plan.md`(本地),阶段细节散落在 `docs/stages/`、`docs/topics/`。

## 特性

**主循环与状态机**
- ReAct 主循环:`think → act → observe` 三分支决策(`control/actions.decide`),`FINISH / CALL_TOOLS / HANDLE_ERROR` 枚举化,循环体只做 `match`
- 状态机:`core/state.py` 声明式转换表,非法迁移抛 `IllegalTransitionError`,终态从表自动派生
- 三种运行模式:`react`(默认,纯 agentic)/ `plan_execute`(Planner 产计划 + Critic 防漂移)/ `workflow`(固定 DAG,LLM 不决策)
- 全 async 事件循环;同步工具 handler 用 `asyncio.to_thread` 包裹

**持久化与恢复**
- durability-first:`Persister` 先落盘 `transcript.jsonl` 再改内存
- `resume()` = 读 transcript 全重放(对齐 Claude Code,无周期快照);崩溃在工具执行中时检测 `pending_tool_calls`,续跑不重跑非幂等工具
- 工具结果落盘 `tool-results/`;`audit.jsonl` 会话级审计

**工具系统**
- `ToolRegistry` + `ToolExecutor` 单工具管道:审计 → jsonschema 校验 → guardrail 门禁 → 幂等缓存 → 熔断 → retry → 幂等写 → fallback
- 内置工具全家桶:read / edit / write / bash / glob / grep / web_search / web_fetch / todo_write / ask_user 等 40+ 个
- `execute_many` 按完成序流式 yield,支持 `depends_on` 拓扑 DAG 并发
- 可靠性独立包:`RetryPolicy`(指数退避+jitter)/ `CircuitBreaker`(per-tool 懒建)/ `IdempotencyStore` / `AuditLogger`

**上下文管理**
- `ContextBuilder` 三层压缩管线(对齐 cc `query.ts`):`ToolResultBudget`(无损落盘)→ `MicroCompact`(低损清老)→ `AutoCompact`(有损摘要),摘要用 cc 式 9 段结构化 prompt
- `ToolResultFormatter` 不截断,大结果全文落盘,保证无损
- `MemoryStore` 文件式长期记忆:MEMORY.md 索引常驻系统提示 + 文件按需召回(关键词匹配),`save_memory` 工具由模型主动调

**安全与可靠**
- Guardrails 四挂载点 `on_input / before_tool / after_tool / on_output`:Prompt 注入 / 权限白名单 / 高风险 HITL 审批 / git 白名单 / PII 脱敏 / 间接注入
- `Workspace` 路径权限:resolve 解 symlink + allows() 目录包含判定,写操作强制校验
- git 集成(CC 对标):只读命令白名单放行,写命令 / `--output` / bare repo 硬拦

**可观测性与多端**
- Tracing:`Tracer`(EventSink)/ `TraceStore`(trace.jsonl)/ `MetricsCollector`(token/tool/retry 聚合)+ `run_meta.json` 侧车(监控 O(1) 读取)
- 多 Agent:`Orchestrator` handoff 循环 + `Blackboard` 共享状态 + 后台 subagent + Task 工具(对话框里直接派小弟)
- 三端共用一套 `Session`:CLI REPL / web(Next.js + SSE 逐字流式 + 断点续传游标)/ Electron desktop
- 事件单点契约 `streaming/events.py`,web 契约事件落盘 `events.jsonl`,`eventReducer` 幂等重放(恢复画面 = 直播画面)

## 目录结构

```
pyproject.toml        # 项目元信息 & 依赖(Python >= 3.12)
agent/                # Agent Runtime 核心(分层,依赖只能向下)
  core/               #   纯数据层:state / messages / models / errors / plan / workspace
  adapters/           #   provider 适配:openai_compat(DeepSeek)/ ark(豆包)
  tools/              #   ToolRegistry + ToolExecutor + 内置工具全家桶
  control/            #   actions 三分支 / loop_detector 软终止 / planner + critic
  context/            #   ContextBuilder:三层压缩 + memory 注入
  memory/             #   MemoryStore 长期记忆
  guardrails/         #   安全护栏四挂载点 + HITL + git 白名单
  reliability/        #   retry / breaker / idempotency / audit
  tracing/            #   Span/Trace + TraceStore + MetricsCollector + eval 工具
  multiagent/         #   Orchestrator / Worker / Reviewer / Blackboard / Handoff
  persist/            #   transcript 落盘 + replay/resume + events.jsonl + run_meta.json
  streaming/          #   events / sink / printer / sse_sink / event_store
  config/             #   AgentConfig + provider 加载
  utils/              #   fileHistory(编辑备份/rewind)+ git 状态
  runtime.py          #   RuntimeContext 依赖容器
  bootstrap.py        #   组合根:build_runtime() 装配共享单例
  session.py          #   Session 多轮会话抽象(CLI/web/desktop 三端共用)
  runner.py           #   主循环机制(三种模式)/ 子 agent 拦截 / resume 续跑
  prompts.py          #   系统提示词(静态核心 + 会话级动态段)
  agentloop.py        #   编排 + REPL(拆后 ~350 行)
chatweb/              # Web 端:backend(async server.py + session_manager)+ frontend(Next.js)
monitor/              # 监控后台:backend + frontend(Vite + shadcn + Recharts)
desktop/              # Electron 桌面端(Next 静态导出共用前端)
tests/                # pytest 单元测试(不依赖真实 LLM,scripted adapter mock)
tests/eval/           # 独立 eval 子系统(BFCL/SR/SE/coding,隔离跑)
stage*_integration.py # 各阶段真实 LLM 联调脚本
scripts/              # 一次性/演示脚本
start.bat / start.ps1 # 一键启动(web / monitor / desktop / repl)
```

## 快速开始

要求 **Python >= 3.12**(仓库 `.python-version` = 3.12;3.9 会在 import 时报错)。

```bash
cd code
# 3.12 venv 激活(python -m venv .venv 后激活)
pip install -e .            # 安装依赖(openai/jsonschema/python-dotenv/pytest/httpx/pyyaml)
# 凭据:在 .env 填入 DEEPSEEK_* / VOLCANO_ENGINE_* / QWEN_API_KEY 等 key(已 gitignore,不进版本库)
python -m agent.agentloop   # 启动 REPL 交互 Agent(默认 provider = DeepSeek)
```

> 默认 provider 走 `config/provider.yaml`(default: `openai_compat`/DeepSeek),`AGENT_PROVIDER` env 可覆盖为 `ark`(豆包)。新增 provider = 实现一个 `BaseModelAdapter` 子类 + 在 `make_adapter` 注册一行 + 在 `.env` 加前缀变量。

## 测试

```bash
python -m pytest tests/ -v                      # 全部单元测试(不依赖真实 LLM,默认忽略 tests/eval)
python -m pytest tests/test_smoke.py -v         # 指定测试(_ScriptedAdapter 全流程冒烟)
python tests/eval/_verify_tasks.py              # eval 子系统(隔离跑各 coding_tasks)
python stage6_integration.py                    # 阶段6 联调(压缩 + memory,deepseek-v4)
python stage7_integration.py                    # 阶段7 联调(plan_execute/workflow 模式)
python stage8_integration.py                    # 阶段8 联调(guardrails/HITL 审批)
python stage10_integration.py                   # 阶段10 联调(多 Agent/Task 工具)
```

> 测试不依赖真实 LLM:`_ScriptedAdapter` 按脚本返回固定 `ModelResponse`,新阶段测试沿用该模式,只需 mock `call_llm` 即可被 `stream_llm` 透明复用。真实 API 只做最终联调(`stage*_integration.py`)。

## 三端启动

一键启动(Windows 桌面):`start.bat`,选项:`web` | `monitor` | `desktop` | `repl` | `all` | `check`。

| 端        | 前端             | 后端             | 端口                                  | 手动启动 |
|-----------|------------------|------------------|---------------------------------------|----------|
| REPL     | TUI              | —                | —                                     | `python -m agent.agentloop` |
| Web      | Next.js :3000    | async server :8000 | <http://localhost:3000>               | `npm run dev` + `python -m chatweb.backend.server` |
| Monitor  | Vite :5173       | server :8002     | <http://localhost:5173>               | `npm run dev` + `python -m monitor.backend.server` |
| Desktop  | Electron :4173   | 自动复用 :8000   | <http://127.0.0.1:4173>               | `npm start`(需先 `npm run build` 出静态导出) |

## 阶段路线(面试学习主线)

| 阶段 | 主题 | 状态 |
|------|------|------|
| 0 | 环境与最小闭环 | ✅ |
| 1 | 消息模型与持久化地基 | ✅ |
| 2 | ReAct 决策与状态机 | ✅ |
| 3 | 工具注册与执行管道 | ✅ |
| 4 | 可靠性(retry/breaker/idempotency/audit) | ✅ |
| 5 | transcript 持久化 + resume/replay | ✅ |
| 6 | 上下文压缩 + 长期记忆 | ✅ |
| 7 | Planning(plan_execute/workflow) | ✅ |
| 8 | Guardrails + HITL + Workspace | ✅ |
| 9 | Tracing / 监控 / web 子系统 | ✅ |
| 10 | 多 Agent / Task 工具 / Session 三端共用 | ✅ |
| 11 | 系统设计整合 | ⏳ 未开始 |

阶段细节:每阶段 `docs/stages/stageN-plan` / `stageN-impl` + `journal-stageN` + `checkpoint-*` + `answer-stageN`;跨阶段横切见 `docs/topics/`(持久化/流式/工作空间/async/提示词/HITL 设计);子系统方向见 `docs/web/`、`docs/monitoring/`、`docs/testing/`、`docs/tools/`、`docs/cc-reference/`。

## 关键设计选择

- **持久化优先(log-then-append)**:每条消息先落盘再改内存,`resume()` 即全重放,无周期快照 —— 对齐 Claude Code 的 TranscriptMessage 模型
- **消息与轨迹分离**:`messages` 是"给模型的上下文"(可压缩裁剪),`steps` 是"执行轨迹"(只增不删,审计/重放用)
- **压缩不破坏无损**:`ToolResultFormatter` 只格式化不截断,大结果交 `ToolResultBudget` 落盘原始全文;截断会破坏恢复后的上下文完整性
- **events 单点契约**:web/SSE 前端消费的 8 种事件在 `streaming/events.py` 单点判定,前端 `lib/events.ts` 是它的 TS 镜像,`EventStore` 把契约事件逐条落盘补上耐久层
- **provider 格式收敛**:content 恒为文本;assistant 的 tool_calls 存 `meta["tool_calls"]`,工具结果存 `meta["tool_call_id"]`,适配器只在 `_to_*` 转 wire 格式 —— 避免 provider 格式泄漏进核心层

## 文档

> `docs/` 目录已被 gitignore(个人学习笔记,不进版本库),以下文档仅存于本地仓库:

- `docs/stages/agent-dev-plan.md` — 11 阶段开发总计划(入口)
- `docs/topics/` — 横切主题:持久化 / 流式 / 工作空间 / async / 提示词 / HITL 设计
- `docs/monitoring/monitor-dashboard-plan.md` — 监控后台实现指南
- `docs/web/` — web 子系统(传输层 / 事件契约 / transport-layer-design)
- `docs/cc-reference/` — Claude Code 对标分析(44 工具 / git 集成 / compact prompt 等)
- 仓库根 `REDEME.md` — 面试学习仓库总览(简历 / 复盘 / 八股)

## License / 致谢

个人面试学习项目。实现参考了 Claude Code(Agent SDK)的工程实践与公开设计,代码为本人逐阶段手写实现。