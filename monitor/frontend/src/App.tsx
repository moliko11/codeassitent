import { createBrowserRouter, Navigate } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { DashboardPage } from "./pages/DashboardPage";
import { RunsPage } from "./pages/RunsPage";
import { RunDetailPage } from "./pages/RunDetailPage";
import { StatsPage } from "./pages/StatsPage";
import { ToolsPage } from "./pages/ToolsPage";
import { SystemPromptPage } from "./pages/SystemPromptPage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: "runs", element: <RunsPage /> },
      { path: "runs/:runId", element: <RunDetailPage /> },
      { path: "stats", element: <StatsPage /> },
      { path: "tools", element: <ToolsPage /> },
      { path: "prompt", element: <SystemPromptPage /> },
    ],
  },
  { path: "*", element: <Navigate to="/" replace /> },
]);
