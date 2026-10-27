import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  Bot,
  Brain,
  Cpu,
  FlaskConical,
  KeyRound,
  LayoutDashboard,
  Menu,
  Moon,
  Network,
  ShieldCheck,
  Sparkles,
  Sun,
  Workflow,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

const NAV = [
  { to: "/experiment", label: "Guided experiment", icon: Sparkles },
  { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/runs", label: "Execution Studio", icon: Activity },
  { to: "/memory", label: "Memory Explorer", icon: Brain },
  { to: "/control", label: "Control Room", icon: ShieldCheck },
  { to: "/orchestration", label: "Orchestration Lab", icon: Workflow },
  { to: "/replay", label: "Replay Lab", icon: FlaskConical },
];

function Logo() {
  return (
    <div className="flex items-center gap-2.5 px-2">
      <div className="grid size-8 place-items-center rounded-lg bg-primary/15 text-primary">
        <Network className="size-4.5" />
      </div>
      <div className="leading-tight">
        <div className="text-sm font-bold tracking-wide">MINDMESH</div>
        <div className="text-[10.5px] text-muted-foreground">Studio</div>
      </div>
    </div>
  );
}

function useTheme() {
  const [dark, setDark] = useState(() => {
    try {
      const v = localStorage.getItem("mindmesh.theme");
      return v ? v === "dark" : true;
    } catch {
      return true;
    }
  });
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    try {
      localStorage.setItem("mindmesh.theme", dark ? "dark" : "light");
    } catch {
      /* ignore */
    }
  }, [dark]);
  return { dark, toggle: () => setDark((d) => !d) };
}

export function Layout() {
  const { dark, toggle } = useTheme();
  const [open, setOpen] = useState(false);
  const me = useQuery({ queryKey: ["me"], queryFn: api.me, retry: false });
  const pending = useQuery({
    queryKey: ["approvals", "pending"],
    queryFn: () => api.approvals("pending"),
    refetchInterval: 4000,
    retry: false,
  });
  const nPending = pending.data?.length ?? 0;
  // Agents registered with their own (non-scripted) models, e.g. a LangChain or Ollama agent.
  const realModels = (me.data?.agent_models ?? []).filter((m) => !m.startsWith("scripted:"));

  const nav = (
    <nav className="flex flex-col gap-0.5">
      {NAV.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          onClick={() => setOpen(false)}
          className={({ isActive }) =>
            cn(
              "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground",
              isActive && "bg-accent font-medium text-accent-foreground",
            )
          }
        >
          <Icon className="size-4" />
          <span>{label}</span>
          {to === "/experiment" && (
            <span className="ml-auto whitespace-nowrap rounded-full bg-primary/15 px-1.5 text-[10px] font-semibold text-primary">start here</span>
          )}
          {to === "/control" && nPending > 0 && (
            <span className="ml-auto rounded-full bg-warning px-1.5 text-[10px] font-semibold text-black">{nPending}</span>
          )}
        </NavLink>
      ))}
    </nav>
  );

  return (
    <div className="flex h-full">
      <aside className="hidden w-60 shrink-0 flex-col gap-6 border-r bg-card/40 p-3 md:flex">
        <div className="pt-1">
          <Logo />
        </div>
        {nav}
        <div className="mt-auto space-y-2 text-xs">
          <NavLink
            to="/settings"
            className={({ isActive }) =>
              cn(
                "flex items-center gap-2 rounded-md px-2.5 py-2 text-muted-foreground hover:bg-accent",
                isActive && "bg-accent text-accent-foreground",
              )
            }
          >
            <KeyRound className="size-4" /> API key & project
          </NavLink>
          <div className="px-2.5 text-[11px] text-muted-foreground">
            project:{" "}
            <span className="font-medium text-foreground" data-testid="project-name">
              {me.data?.project_name ?? (me.isError ? "not connected" : "…")}
            </span>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center gap-2 border-b px-4">
          <Button variant="ghost" size="icon" className="md:hidden" onClick={() => setOpen(true)} aria-label="Menu">
            <Menu />
          </Button>
          <div className="md:hidden">
            <Logo />
          </div>
          <div className="ml-auto flex items-center gap-1">
            {me.isError && (
              <span className="mr-2 text-xs text-destructive">API unreachable or invalid key — see Settings</span>
            )}
            {me.data && (
              <span
                className="mr-1 inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] text-muted-foreground"
                title={
                  me.data.model_mode === "live"
                    ? "New runs use this live model (MINDMESH_MODEL). The guided experiment can still use the demo model."
                    : "No live model configured: agents use their deterministic scripted models. Set MINDMESH_MODEL=ollama:qwen3:4b for a real model."
                }
                data-testid="server-mode"
              >
                {me.data.model_mode === "live" || realModels.length ? <Cpu className="size-3.5 text-primary" /> : <Bot className="size-3.5 text-info" />}
                {me.data.model_mode === "live"
                  ? `Live model · ${me.data.live_model}`
                  : realModels.length
                    ? `Agents · ${realModels.join(", ")}`
                    : "Demo mode · scripted models"}
              </span>
            )}
            <Button variant="ghost" size="icon" onClick={toggle} aria-label="Toggle theme">
              {dark ? <Sun /> : <Moon />}
            </Button>
          </div>
        </header>
        {me.data?.role === "read" && (
          <div className="border-b bg-info/10 px-4 py-2 text-xs text-foreground" data-testid="read-only-banner">
            <span className="font-medium">Public read-only demo.</span> Explore runs, traces, memories and policies;
            changes are disabled. Developers can connect with their own key in{" "}
            <NavLink to="/settings" className="underline underline-offset-2">
              Settings
            </NavLink>
            .
          </div>
        )}
        <main className="min-h-0 flex-1 overflow-auto p-4 md:p-6">
          <Outlet />
        </main>
      </div>

      {open && (
        <div className="fixed inset-0 z-50 md:hidden">
          <div className="absolute inset-0 bg-black/50" onClick={() => setOpen(false)} />
          <div className="absolute inset-y-0 left-0 flex w-64 flex-col gap-6 border-r bg-background p-3">
            <div className="flex items-center justify-between">
              <Logo />
              <Button variant="ghost" size="icon" onClick={() => setOpen(false)} aria-label="Close menu">
                <X />
              </Button>
            </div>
            {nav}
            <NavLink to="/settings" onClick={() => setOpen(false)} className="px-2.5 text-sm text-muted-foreground">
              API key & project
            </NavLink>
          </div>
        </div>
      )}
    </div>
  );
}
