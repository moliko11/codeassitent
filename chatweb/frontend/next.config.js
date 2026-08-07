/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // react-syntax-highlighter ships ESM that Next must transpile.
  transpilePackages: ["react-syntax-highlighter"],
  // Phase 2 §2.2:静态导出(web/桌面共用一份产物)。前端已删 app/api BFF 路由、直连
  // http://localhost:8000(后端 CORS 全开),web 纯静态托管、桌面 Electron 壳 loadURL 都用 out/。
  output: "export",
};

module.exports = nextConfig;
