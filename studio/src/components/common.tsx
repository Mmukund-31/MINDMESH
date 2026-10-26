import * as React from "react";
import { AlertTriangle, CheckCircle2, Circle, Clock, Loader2, PauseCircle, XCircle } from "lucide-react";
import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const STATUS: Record<string, { variant: BadgeVariant; icon: React.ElementType; label?: string }> = {
  succeeded: { variant: "success", icon: CheckCircle2 },
  ok: { variant: "success", icon: CheckCircle2 },
  final: { variant: "success", icon: CheckCircle2, label: "final answer" },
  approved: { variant: "success", icon: CheckCircle2 },
  active: { variant: "success", icon: Circle },
  allow: { variant: "success", icon: CheckCircle2 },
  failed: { variant: "destructive", icon: XCircle },
  error: { variant: "destructive", icon: XCircle },
  deny: { variant: "destructive", icon: XCircle },
  blocked: { variant: "destructive", icon: XCircle },
  rejected: { variant: "destructive", icon: XCircle },
  retracted: { variant: "destructive", icon: XCircle },
  invalid_args: { variant: "destructive", icon: AlertTriangle, label: "invalid args" },
  cancelled: { variant: "secondary", icon: XCircle },
  skipped: { variant: "secondary", icon: Circle },
  superseded: { variant: "secondary", icon: Circle },
  expired: { variant: "secondary", icon: Clock },
  running: { variant: "info", icon: Loader2 },
  ready: { variant: "info", icon: Circle },
  pending: { variant: "outline", icon: Clock },
  waiting_approval: { variant: "warning", icon: PauseCircle, label: "awaiting approval" },
  pending_approval: { variant: "warning", icon: PauseCircle, label: "awaiting approval" },
  require_approval: { variant: "warning", icon: PauseCircle, label: "needs approval" },
};

export function StatusBadge({ status, className }: { status: string | null | undefined; className?: string }) {
  const s = STATUS[status ?? ""] ?? { variant: "outline" as BadgeVariant, icon: Circle };
  const Icon = s.icon;
  return (
    <Badge variant={s.variant} className={className} data-testid={`status-${status}`}>
      <Icon className={cn(status === "running" && "animate-spin")} />
      {s.label ?? status?.replace(/_/g, " ")}
    </Badge>
  );
}

export function PageHeader({
  title,
  description,
  icon: Icon,
  actions,
}: {
  title: string;
  description?: string;
  icon?: React.ElementType;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 pb-4">
      <div className="flex items-start gap-3">
        {Icon && (
          <div className="mt-0.5 rounded-lg bg-primary/12 p-2 text-primary">
            <Icon className="size-5" />
          </div>
        )}
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
          {description && <p className="text-sm text-muted-foreground">{description}</p>}
        </div>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Stat({
  label,
  value,
  hint,
  tone,
  icon: Icon,
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  tone?: "good" | "bad" | "warn";
  icon?: React.ElementType;
}) {
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>{label}</span>
        {Icon && <Icon className="size-4" />}
      </div>
      <div
        className={cn(
          "mt-1 text-2xl font-semibold tabular-nums",
          tone === "good" && "text-success",
          tone === "bad" && "text-destructive",
          tone === "warn" && "text-warning",
        )}
      >
        {value}
      </div>
      {hint && <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div>}
    </Card>
  );
}

export function EmptyState({ title, children, icon: Icon }: { title: string; children?: React.ReactNode; icon?: React.ElementType }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed p-8 text-center">
      {Icon && <Icon className="size-6 text-muted-foreground" />}
      <div className="text-sm font-medium">{title}</div>
      {children && <div className="max-w-md text-xs text-muted-foreground">{children}</div>}
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <div className="flex items-start gap-2 rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
      <AlertTriangle className="mt-0.5 size-4 shrink-0" />
      <span>{msg}</span>
    </div>
  );
}

export function Json({ value, className }: { value: unknown; className?: string }) {
  return (
    <pre
      className={cn(
        "max-h-80 overflow-auto rounded-md bg-muted/60 p-2.5 font-mono text-[11px] leading-relaxed whitespace-pre-wrap break-all",
        className,
      )}
    >
      {typeof value === "string" ? value : JSON.stringify(value, null, 2)}
    </pre>
  );
}

export function KV({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1 text-xs">
      <span className="text-muted-foreground">{k}</span>
      <span className="text-right font-medium">{children}</span>
    </div>
  );
}

export function Mono({ className, ...props }: React.ComponentProps<"span">) {
  return <span className={cn("font-mono text-[11px]", className)} {...props} />;
}

export function ScoreBar({ value, className }: { value: number; className?: string }) {
  return (
    <div className={cn("h-1.5 w-16 overflow-hidden rounded-full bg-muted", className)}>
      <div className="h-full rounded-full bg-primary" style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }} />
    </div>
  );
}
