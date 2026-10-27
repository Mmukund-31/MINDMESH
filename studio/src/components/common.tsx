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
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 pb-3">
      <div className="flex min-w-0 items-center gap-2.5">
        {Icon && <Icon className="size-4 shrink-0 text-muted-foreground" />}
        <h1 className="text-base font-semibold tracking-tight">{title}</h1>
        {description && <p className="hidden truncate text-xs text-muted-foreground lg:block">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

/** A section with a header strip. The workbench's basic container. */
export function Panel({
  title,
  description,
  icon: Icon,
  actions,
  children,
  className,
  bodyClassName,
  ...props
}: {
  title?: React.ReactNode;
  description?: React.ReactNode;
  icon?: React.ElementType;
  actions?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
  bodyClassName?: string;
} & Omit<React.ComponentProps<"section">, "title">) {
  return (
    <section className={cn("flex min-w-0 flex-col rounded-lg border bg-card", className)} {...props}>
      {(title || actions) && (
        <header className="flex min-h-10 flex-wrap items-center justify-between gap-2 border-b px-3 py-2">
          <div className="min-w-0">
            <h2 className="flex items-center gap-1.5 text-xs font-semibold">
              {Icon && <Icon className="size-3.5 text-muted-foreground" />}
              {title}
            </h2>
            {description && <p className="mt-0.5 text-[11px] text-muted-foreground">{description}</p>}
          </div>
          {actions && <div className="flex items-center gap-1.5">{actions}</div>}
        </header>
      )}
      <div className={cn("min-w-0 flex-1", bodyClassName)}>{children}</div>
    </section>
  );
}

const DOT: Record<string, string> = {
  succeeded: "bg-success", ok: "bg-success", final: "bg-success", allow: "bg-success", approved: "bg-success",
  active: "bg-success", healthy: "bg-success",
  failed: "bg-destructive", error: "bg-destructive", deny: "bg-destructive", blocked: "bg-destructive",
  rejected: "bg-destructive", invalid_args: "bg-destructive", unhealthy: "bg-destructive", retracted: "bg-destructive",
  waiting_approval: "bg-warning", pending_approval: "bg-warning", require_approval: "bg-warning", warn: "bg-warning",
  running: "bg-info", ready: "bg-info", pending: "bg-muted-foreground/60",
};

/** A status as a dot; pulses while running. */
export function StatusDot({ status, className }: { status: string | null | undefined; className?: string }) {
  const color = DOT[status ?? ""] ?? "bg-muted-foreground/50";
  return (
    <span className={cn("relative inline-flex size-2 shrink-0", className)} title={status?.replace(/_/g, " ")}>
      {status === "running" && <span className={cn("absolute inset-0 animate-ping rounded-full opacity-60", color)} />}
      <span className={cn("relative inline-flex size-2 rounded-full", color)} />
    </span>
  );
}

/** A compact number with a label, for status strips. */
export function Metric({
  label,
  value,
  hint,
  tone,
  className,
  ...props
}: {
  label: React.ReactNode;
  value: React.ReactNode;
  hint?: React.ReactNode;
  tone?: "good" | "bad" | "warn" | "muted";
  className?: string;
} & Omit<React.ComponentProps<"div">, "title">) {
  return (
    <div className={cn("min-w-0 px-3 py-2.5", className)} {...props}>
      <div className="truncate text-[11px] text-muted-foreground">{label}</div>
      <div
        className={cn(
          "mt-0.5 text-lg leading-6 font-semibold tabular-nums",
          tone === "good" && "text-success",
          tone === "bad" && "text-destructive",
          tone === "warn" && "text-warning",
          tone === "muted" && "text-muted-foreground",
        )}
      >
        {value}
      </div>
      {hint && <div className="truncate text-[11px] text-muted-foreground">{hint}</div>}
    </div>
  );
}

/** A monospace id: shortened for display, full id in the tooltip, copied on click. */
export function IdChip({ id, full, className }: { id: string | null | undefined; full?: boolean; className?: string }) {
  const [copied, setCopied] = React.useState(false);
  if (!id) return <span className="text-muted-foreground">–</span>;
  const i = id.indexOf("_");
  const label = full || i < 0 ? id : `${id.slice(0, i)}…${id.slice(-6)}`;
  return (
    <button
      type="button"
      title={copied ? "copied" : `${id} (click to copy)`}
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        navigator.clipboard?.writeText(id).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1200);
        });
      }}
      className={cn("cursor-copy font-mono text-[11px] text-muted-foreground hover:text-foreground", className)}
    >
      {copied ? "copied" : label}
    </button>
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
    <div className="flex flex-col items-center justify-center gap-1.5 rounded-lg border border-dashed p-6 text-center">
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
        "max-h-80 overflow-auto rounded-md border bg-background/60 p-2.5 font-mono text-[11px] leading-relaxed whitespace-pre-wrap break-all",
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
