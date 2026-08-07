import { NavLink, Outlet } from "react-router-dom";
import { LayoutDashboard, ListOrdered, BarChart3, FileText, Activity } from "lucide-react";
import { cn } from "@/lib/cn";
import { ThemeToggle } from "./ThemeToggle";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/runs", label: "Runs", icon: ListOrdered, end: false },
  { to: "/stats", label: "统计", icon: BarChart3, end: false },
  { to: "/prompt", label: "系统提示词", icon: FileText, end: false },
];

function Sidebar() {
  return (
    <aside className="flex w-56 shrink-0 flex-col border-r bg-[var(--card)]">
      <div className="flex items-center gap-2 border-b px-5 py-4">
        <Activity className="h-5 w-5 text-[var(--primary)]" />
        <div className="leading-tight">
          <div className="text-sm font-semibold">ez-interview</div>
          <div className="text-[11px] text-[var(--muted-foreground)]">监控后台</div>
        </div>
      </div>
      <nav className="flex-1 space-y-1 p-3">
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                  : "text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)]",
              )
            }
          >
            <n.icon className="h-4 w-4" />
            {n.label}
          </NavLink>
        ))}
      </nav>
      <div className="border-t p-3">
        <ThemeToggle />
      </div>
    </aside>
  );
}

export function AppShell() {
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}
