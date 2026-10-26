import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function fmtNum(n: number | null | undefined, digits = 0): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "–";
  return n.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

export function fmtPct(n: number | null | undefined): string {
  if (n === null || n === undefined) return "–";
  return `${Math.round(n * 100)}%`;
}

export function fmtMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "–";
  if (ms < 1) return "<1 ms";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

export function parseTs(iso: string): Date {
  return new Date(/Z$|[+-]\d\d:\d\d$/.test(iso) ? iso : iso + "Z");
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "–";
  const s = Math.round((Date.now() - parseTs(iso).getTime()) / 1000);
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function shortId(id: string | null | undefined): string {
  if (!id) return "–";
  const i = id.indexOf("_");
  return i > 0 ? `${id.slice(0, i)}…${id.slice(-6)}` : id.slice(-8);
}

export function durationMs(a?: string | null, b?: string | null): number | null {
  if (!a || !b) return null;
  return parseTs(b).getTime() - parseTs(a).getTime();
}
