# 监控后台 React 前端

ez-interview 监控后台的 React 19 仪表盘,只读后端 FastAPI API,对标 Langfuse 观测体验。设计稿见 [docs/monitoring/monitor-frontend-design.md](../../../docs/monitoring/monitor-frontend-design.md)。

## 技术栈

Vite + React 19 + TypeScript + Tailwind 3.4 + shadcn/ui + Recharts + @tanstack/react-query + react-router-dom。复用 `code/chatweb/frontend/` 的 CSS 变量主题系统 + `cn()`。

## 启动(前后端两个进程)

```bash
# 终端 1:后端(必须从 code/ 启动,PERSIST_ROOT 是相对路径)
cd code
python -m monitor.backend.server          # http://127.0.0.1:8000

# 终端 2:前端
cd code/monitor/frontend
npm install                                # 首次
npm run dev                                # http://localhost:5173

# 浏览器开 http://localhost:5173
```

前端经 Vite proxy 把 `/api/*` 代理到 `127.0.0.1:8000`(同源,免 CORS,见 `vite.config.ts`)。

## 页面

| 路由 | 内容 |
|---|---|
| `/` | Dashboard:KPI 卡 + token 趋势 + model 分布 + 命中率/成功率趋势 + 近期 runs |
| `/runs` | 会话列表:全字段表格 + 排序 + status/model 筛选 |
| `/runs/:id` | Run 详情(核心,5 Tab):火焰图 / 消息流 / 系统提示词 / Token 明细 / 上下文快照(预留) |
| `/stats` | 统计:按 model/天/状态分布 + 工具分析(预留)+ 反馈 |
| `/prompt` | 全局默认系统提示词分层 |

## 后端 API(只读,契约不变)

| 端点 | 返回 |
|---|---|
| `GET /api/stats` | 跨 run 聚合(token/缓存/成功率/by_day/by_model) |
| `GET /api/runs` | 会话列表(run_meta 摘要) |
| `GET /api/runs/{id}` | `{meta, report}` |
| `GET /api/runs/{id}/trace` | span 树 JSON(火焰图) |
| `GET /api/runs/{id}/transcript?limit=N` | 消息流 |
| `GET /api/feedback` | 反馈聚合 |
| `GET /api/system_prompt` | 系统提示词分层 |

## 火焰图 / 消息流约定

- **火焰图**:span 按 `parent_id` 建树,垂直 icicle(每行一个 span,缩进=深度,宽∝`duration_ms/runDur`),色按 type;子 agent span(`attrs.agent_id` 非空)红边框 + [子]。
- **消息流**:同一条 assistant 多个 `tool_calls` = 并行批次(execute_many 同轮并发),标「并行 N 个」;`tool_result` 折叠长内容;子 agent record 加 [agent_id] 徽标。
- **Token 明细**:堆叠 缓存命中 + 新输入(input-cached) + 输出,总和 = input+output(cached 是 input 子集,不重复计)。

## 观测性预留(待后端)

- 上下文快照(observability-todo A):待 `ContextBuilder.build` 落 `context_snapshots.jsonl` + `/api/runs/{id}/context`,Run 详情「上下文快照」Tab 填充(消息按 origin 分层 + token 占比,对标 Langfuse 的差异点)。
- 工具分析 `/api/stats/tools`:待后端聚合 tool span(latency P50/P95/重试)。
- cost:`cached_tokens` 已采,待 pricing 表(§8 TODO)。

## 构建

```bash
npm run build      # tsc -b + vite build -> dist/
```

生产可由后端挂载 `dist/` 静态文件,或反向代理。本期 dev 优先。
