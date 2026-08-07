// desktop/main.js - Electron 主进程(Phase 2 §2.1/§2.6)
//
// 职责:spawn 本地 FastAPI 后端(chatweb.backend.server,:8000)+ 极简静态 server 服务
// chatweb/frontend/out(静态导出产物)+ 单窗口 + 系统托盘 + 退出时 kill 后端。
// 后端必须在 code/ 下启动(PERSIST_ROOT 相对路径),所以 spawn 的 cwd 固定为仓库 code/。
//
// 关键取舍:用「静态 server + loadURL」而不是 loadFile —— Next 静态导出的资源引用是
// 绝对路径(/_next/...),file:// 下全 404;且 file:// 的 opaque origin 对跨源 fetch 与
// Monaco web worker 有额外限制。40 行 Node http server 一次性消除整类问题。
const path = require("path");
const http = require("http");
const fs = require("fs");
const { execFile, execFileSync, spawn, spawnSync } = require("child_process");
const { app, BrowserWindow, Tray, Menu, dialog, ipcMain, shell } = require("electron");

const CODE_DIR = path.resolve(__dirname, ".."); // code/ —— uvicorn 必须在此 cwd 下跑
const OUT_DIR = path.join(CODE_DIR, "chatweb", "frontend", "out");
const BACKEND_PORT = process.env.AGENT_PORT || "8000";
const BACKEND_URL = `http://localhost:${BACKEND_PORT}`;
const TRAY_ICON = path.join(__dirname, "assets", "tray.png");

let win = null;
let tray = null;
let backendProc = null;
let staticServer = null;
let staticPort = 0;
let quitting = false;

// ── 找 Python 3.12(拿真 exe,绕开 WindowsApps shim)──
async function resolvePython() {
  const candidates = [process.env.EZ_PYTHON, process.env.PYTHON, "python", "py"];
  for (const c of candidates) {
    if (!c) continue;
    try {
      const { stdout } = await new Promise((res, rej) => {
        execFile(c, ["-c", "import sys; print(sys.executable)"], { timeout: 5000 }, (e, so) =>
          e ? rej(e) : res({ stdout: so }),
        );
      });
      const exe = String(stdout).trim();
      if (exe && fs.existsSync(exe)) return exe;
    } catch {
      /* 试下一个 */
    }
  }
  return null;
}

// ── spawn 后端(uvicorn,同进程不 fork worker;kill() 即杀)──
function spawnBackend(pyExe) {
  const child = spawn(pyExe, ["-m", "chatweb.backend.server"], {
    cwd: CODE_DIR,
    shell: false, // 直接 exec 真 exe,避免只杀到 cmd 壳
    env: {
      ...process.env,
      AGENT_PORT: BACKEND_PORT,
      PYTHONUTF8: "1",
      PYTHONUNBUFFERED: "1",
    },
  });
  child.stdout.on("data", (d) => process.stdout.write(d));
  child.stderr.on("data", (d) => process.stderr.write(d));
  child.on("exit", (code) => {
    if (!quitting && code !== 0) {
      dialog.showErrorBox("后端异常退出", `uvicorn 退出码 ${code}(见上方日志)`);
    }
  });
  child.on("error", (e) => {
    dialog.showErrorBox("无法启动后端", String(e.message || e));
  });
  return child;
}

// ── kill 后端(Windows:kill() + taskkill /T 杀进程树兜底)──
function killBackend() {
  if (backendProc && backendProc.pid) {
    const pid = backendProc.pid;
    try { backendProc.kill(); } catch { /* 已退出 */ }
    try { spawnSync("taskkill", ["/pid", String(pid), "/T", "/F"]); } catch { /* 忽略 */ }
  }
  backendProc = null;
}

// ── 极简静态 server(只读服务 out/,禁止目录穿越)──
const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
  ".map": "application/json",
};
function createStaticServer() {
  return http.createServer((req, res) => {
    let urlPath = decodeURIComponent((req.url || "/").split("?")[0]);
    if (urlPath === "/") urlPath = "/index.html";
    const filePath = path.normalize(path.join(OUT_DIR, urlPath));
    if (!filePath.startsWith(OUT_DIR)) {
      res.writeHead(403);
      res.end("Forbidden");
      return;
    }
    fs.readFile(filePath, (err, data) => {
      if (err) {
        res.writeHead(404);
        res.end("Not Found");
        return;
      }
      res.writeHead(200, { "Content-Type": MIME[path.extname(filePath)] || "application/octet-stream" });
      res.end(data);
    });
  });
}

function getFreePort(start) {
  return new Promise((resolve, reject) => {
    const tryPort = (p) => {
      const srv = createStaticServer();
      srv.once("error", (e) => {
        if (e.code === "EADDRINUSE" && p < start + 10) tryPort(p + 1);
        else reject(e);
      });
      srv.listen(p, "127.0.0.1", () => {
        srv.close(() => resolve(p));
      });
    };
    tryPort(start);
  });
}

function createWindow() {
  win = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 960,
    minHeight: 640,
    title: "ez-interview Agent",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  win.loadURL(`http://127.0.0.1:${staticPort}`);
  // 关闭按钮 -> 最小化到托盘(真正退出走托盘菜单「退出」)
  win.on("close", (e) => {
    if (!quitting) {
      e.preventDefault();
      win.hide();
    }
  });
  // 外部链接(markdown 里的 URL)交给系统浏览器,不在应用窗口里跳走
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/i.test(url)) shell.openExternal(url);
    return { action: "deny" };
  });
}

function createTray() {
  tray = new Tray(TRAY_ICON);
  tray.setToolTip("ez-interview Agent");
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: "显示窗口", click: () => { win.show(); win.focus(); } },
      { type: "separator" },
      {
        label: "退出",
        click: () => {
          quitting = true;
          app.quit();
        },
      },
    ]),
  );
  tray.on("click", () => { win.show(); win.focus(); });
}

// ── IPC 契约(Phase 2 §2.6,preload 暴露)──
function registerIpc() {
  ipcMain.handle("app:getBackendUrl", () => BACKEND_URL);
  ipcMain.handle("approval:ask", async (_event, req) => {
    // req = { requestId, toolName, reason, arguments };dialog.showMessageBox 弹原生确认框。
    const { response } = await dialog.showMessageBox(win, {
      type: "question",
      title: "需人工批准",
      noLink: true,
      buttons: ["允许执行", "拒绝"],
      defaultId: 0,
      cancelId: 1,
      message: `工具 ${req?.toolName || "?"} 需要你的确认`,
      detail: `${req?.reason || ""}\n\n参数:\n${JSON.stringify(req?.arguments ?? {}, null, 2)}`,
    });
    return { allow: response === 0, reason: response === 0 ? "" : "用户拒绝执行" };
  });
}

app.whenReady().then(async () => {
  const pyExe = await resolvePython();
  if (!pyExe) {
    dialog.showErrorBox(
      "未找到 Python",
      "请安装 Python 3.12,或在环境变量 EZ_PYTHON / PYTHON 指向 python.exe(见 desktop/README.md)",
    );
    app.quit();
    return;
  }
  if (!fs.existsSync(path.join(OUT_DIR, "index.html"))) {
    dialog.showErrorBox(
      "缺少前端产物",
      `未找到 ${path.join(OUT_DIR, "index.html")}。请先执行:cd chatweb/frontend && npm run build`,
    );
    app.quit();
    return;
  }

  staticPort = await getFreePort(4173);
  staticServer = createStaticServer();
  staticServer.listen(staticPort, "127.0.0.1");

  backendProc = spawnBackend(pyExe);
  registerIpc();
  createWindow();
  createTray();
});

// 单实例锁:重复启动 -> 恢复已有窗口
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (win) { if (win.isMinimized()) win.restore(); win.show(); win.focus(); }
  });
}

// 退出清理
app.on("before-quit", () => { quitting = true; killBackend(); });
process.on("exit", killBackend); // 最后防线(例如崩溃路径)
app.on("window-all-closed", () => {
  // 常驻托盘:窗口全关不退出(退出只能走托盘菜单)。macOS 惯例同此。
});
