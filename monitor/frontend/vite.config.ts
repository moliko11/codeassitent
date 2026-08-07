import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// 前端 5173 -> 后端 8002:Vite proxy /api 同源,免 CORS(设计稿 §5/§8)
// 8000 是 chatweb 后端,monitor 后端默认 8002(server.py __main__ 的 MONITOR_PORT)。
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8002", changeOrigin: true },
    },
  },
});
