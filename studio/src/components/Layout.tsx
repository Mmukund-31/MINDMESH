import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
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
import { api, health } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ErrorBoundary, StatusDot } from "@/components/common";

const NAV = [
  { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/runs", label: "Execution Studio", icon: Activity },
  { to: "/memory", label: "Memory Explorer", icon: Brain },
  { to: "/control", label: "Control Room", icon: ShieldCheck },
  { to: "/orchestration", label: "Orchestration Lab", icon: Workflow },
  { to: "/replay", label: "Replay & Evaluation", icon: FlaskConical },
];

function Logo() {
  return (
    <div className="flex items-center gap-2">
      <div className="grid size-6 place-items-center rounded-md bg-primary/15 text-primary">
        <Network className="size-3.5" />
      </div>
      <span className="text-[13px] font-semibold tracking-tight">MindMesh</span>
      <span className="text-[11px] text-muted-foreground">Studio</span>
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

function NavItem({ to, label, icon: Icon, end, badge, onClick }: {
  to: string; label: string; icon: React.ElementType; end?: boolean; badge?: React.ReactNode; onClick?: () => void;
}) {
  return (
    <NavLink
      to={to}
      end={end}
      onClick={onClick}
      className={({ isActive }) =>
        cn(
          "flex h-8 items-center gap-2.5 rounded-md px-2 text-[13px] text-muted-foreground transition-colors hover:bg-accent/70 hover:text-foreground",
          isActive && "bg-accent font-medium text-foreground",
        )
      }
    >
      <Icon className="size-4 shrink-0" />
      <span className="truncate">{label}</span>
      {badge}
    </NavLink>
  );
}

export function Layout() {
  const { dark, toggle } = useTheme();
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const me = useQuery({ queryKey: ["me"], queryFn: api.me, retry: false });
  const up = useQuery({ queryKey: ["health"], queryFn: health, refetchInterval: 15_000, retry: false });
  const pending = useQuery({
    queryKey: ["approvals", "pending"],
    queryFn: () => api.approvals("pending"),
    refetchInterval: 4000,
    retry: false,
  });
  const nPending = pending.data?.length ?? 0;
  // Agents registered with their own (non-scripted) models, e.g. a LangChain or Ollama agent.
  const realModels = (me.data?.agent_models ?? []).filter((m) => !m.startsWith("scripted:"));
  const healthy = up.data?.status === "ok";

  const nav = (
    <nav className="flex flex-col gap-px">
      {NAV.map((n) => (
        <NavItem
          key={n.to}
          {...n}
          onClick={() => setOpen(false)}
          badge={
            n.to === "/control" && nPending > 0 ? (
              <span className="ml-auto rounded-sm bg-warning/20 px-1.5 text-[10px] font-semibold text-warning tabular-nums" title="pending approvals">
                {nPending}
              </span>
            ) : undefined
          }
        />
      ))}
      <div className="mt-4 mb-1 px-2 text-[10px] font-medium tracking-wider text-muted-foreground/70 uppercase">Learn</div>
      <NavItem to="/experiment" label="Guided experiment" icon={Sparkles} onClick={() => setOpen(false)} />
    </nav>
  );

  const footer = (
    <div className="space-y-1 border-t pt-2 text-[11px]">
      <div className="flex items-center gap-2 px-2 py-1 text-muted-foreground" data-testid="system-status">
        <StatusDot status={up.isLoading ? "pending" : healthy ? "healthy" : "unhealthy"} />
        <span>{up.isLoading ? "connecting…" : healthy ? `API · ${up.data?.database}` : "API unreachable"}</span>
      </div>
      <NavLink
        to="/settings"
        onClick={() => setOpen(false)}
        className={({ isActive }) =>
          cn("flex items-center gap-2 rounded-md px-2 py-1.5 text-muted-foreground hover:bg-accent/70 hover:text-foreground",
            isActive && "bg-accent text-foreground")
        }
      >
        <KeyRound className="size-3.5" />
        <span className="truncate">
          <span className="font-medium text-foreground" data-testid="project-name">
            {me.data?.project_name ?? (me.isError ? "not connected" : "…")}
          </span>
          {me.data && <span> · {me.data.role === "read" ? "read-only" : "admin"}</span>}
        </span>
      </NavLink>
    </div>
  );

  return (
    <div className="flex h-full">
      <aside className="hidden w-52 shrink-0 flex-col border-r bg-card/50 px-2 pb-2 md:flex">
        <div className="flex h-11 items-center px-2">
          <Logo />
        </div>
        {nav}
        <div className="mt-auto">{footer}</div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-11 shrink-0 items-center gap-2 border-b px-3 md:px-4">
          <Button variant="ghost" size="icon" className="md:hidden" onClick={() => setOpen(true)} aria-label="Menu">
            <Menu />
          </Button>
          <div className="md:hidden">
            <Logo />
          </div>
          <div className="ml-auto flex items-center gap-1.5">
            {me.isError && <span className="mr-2 text-xs text-destructive">API unreachable or invalid key — see Settings</span>}
            {me.data && (
              <span
                className="hidden items-center gap-1.5 rounded-md border px-2 py-0.5 text-[11px] text-muted-foreground sm:inline-flex"
                title={
                  me.data.model_mode === "live"
                    ? "New runs use this live model (MINDMESH_MODEL). The guided experiment can still use the demo model."
                    : realModels.length
                      ? "Registered agents use these models."
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
            <Button variant="ghost" size="icon" onClick={toggle} aria-label="Toggle theme" title="Toggle theme">
              {dark ? <Sun /> : <Moon />}
            </Button>
          </div>
        </header>
        {me.data?.role === "read" && (
          <div className="border-b bg-info/10 px-4 py-1.5 text-xs text-foreground" data-testid="read-only-banner">
            <span className="font-medium">Public read-only demo.</span> Explore runs, traces, memories and policies;
            changes are disabled. Developers can connect with their own key in{" "}
            <NavLink to="/settings" className="underline underline-offset-2">
              Settings
            </NavLink>
            .
          </div>
        )}
        <main className="min-h-0 flex-1 overflow-auto px-3 py-4 md:px-5">
          <div className="mx-auto max-w-[1680px]">
            <ErrorBoundary key={location.pathname}>
              <Outlet />
            </ErrorBoundary>
          </div>
        </main>
      </div>

      {open && (
        <div className="fixed inset-0 z-50 md:hidden">
          <div className="absolute inset-0 bg-black/60" onClick={() => setOpen(false)} />
          <div className="absolute inset-y-0 left-0 flex w-60 flex-col border-r bg-background px-2 pb-2">
            <div className="flex h-11 items-center justify-between px-2">
              <Logo />
              <Button variant="ghost" size="icon" onClick={() => setOpen(false)} aria-label="Close menu">
                <X />
              </Button>
            </div>
            {nav}
            <div className="mt-auto">{footer}</div>
          </div>
        </div>
      )}
    </div>
  );
}
