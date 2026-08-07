// Electron preload 注入的桌面端 API(Phase 2 §2.6)。
// 浏览器(web 端)没有 window.electronAPI,前端据此分流:桌面走主进程原生弹窗,web 走内嵌 modal。
interface ElectronAPI {
  isElectron: boolean;
  platform: string;
  getBackendUrl: () => Promise<string>;
  askApproval: (req: {
    requestId: string;
    toolName: string;
    reason: string;
    arguments: Record<string, unknown>;
  }) => Promise<{ allow: boolean; reason: string }>;
}

interface Window {
  electronAPI?: ElectronAPI;
}
