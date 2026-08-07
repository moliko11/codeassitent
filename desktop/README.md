# ez-interview Agent 桌面端(Phase 2)

Electron 壳 + 本地 FastAPI 后端。桌面与 web **共用** `chatweb/frontend/` 一套前端(静态导出产物)。

## 前置

1. **Python 3.12**(项目默认 3.9 会报错;`code/` 的 venv 或系统 3.12 均可)。主进程找解释器顺序:
   `EZ_PYTHON` env → `PYTHON` env → `python` → `py`。拿不到会弹错误框。
2. **`code/.env` 必须存在**(后端 server.py 模块级读 API key,缺 key 直接 raise)。
3. **前端产物已 build**:`cd chatweb/frontend && npm run build`(产出 `out/`,静态导出)。
   缺 `out/index.html` 时启动会弹错误框。

## 启动

```bash
cd code/desktop
npm install        # 首次;.npmrc 已配 npmmirror + electron_mirror(国内镜像)
npm start          # electron . —— spawn 后端(:8000)+ 静态 server + 窗口
```

- 主进程自动 spawn `python -m chatweb.backend.server`(cwd=`code/`),stdout/stderr 透传本终端。
- 后端端口:`AGENT_PORT` env 覆盖(默认 8000)。**8000 必须空闲**(monitor 已让位 8002)。
- 前端地址:`http://127.0.0.1:4173`(被占自动 +1)。

## 使用

- 关闭按钮 → 最小化到托盘;真正退出走托盘菜单「退出」。退出会 kill 后端进程树。
- 单实例锁:重复 `npm start` 会恢复已有窗口。
- **原生审批弹窗**:agent 触发 HITL(git 写命令等)时,主进程弹系统对话框,允许/拒绝后回传后端。
- 「文件历史」按钮:该会话编辑过的文件版本链 + Monaco diff(当前 vs 编辑前)。

## 常见问题

- **Electron 二进制下载慢/失败**:确认 `.npmrc` 在;装完校验 `node_modules/electron/dist/electron.exe` 存在。
- **改了后端代码却报旧错**:Windows mtime 精度坑,清 `__pycache__`:
  `python -c "import shutil, pathlib; [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__')]"`
- **8000 被占**:设 `AGENT_PORT=8001 npm start`,同时把 `chatweb/frontend/.env.local` 的
  `NEXT_PUBLIC_AGENT_API` 改成 8001 并重新 `npm run build`(静态导出构建期内联)。

## 打包(未做,TODO)

本期只保证开发态 `npm start` 跑通。正式分发需 `electron-builder`(安装器/图标/asar,见
`docs/web/fullstack-dev-plan.md` §Phase 2 收尾)。
