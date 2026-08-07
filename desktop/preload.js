// desktop/preload.js - contextBridge 暴露最小 API(Phase 2 §2.6)
// contextIsolation 开启,渲染进程只能拿到这里白名单暴露的东西,不能碰 Node。
// window.electronAPI 存在 = 桌面端;web 浏览器里 undefined,前端据此分流(原生弹窗 vs 内嵌 modal)。
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("electronAPI", {
  isElectron: true,
  platform: process.platform,
  getBackendUrl: () => ipcRenderer.invoke("app:getBackendUrl"),
  askApproval: (req) => ipcRenderer.invoke("approval:ask", req),
});
