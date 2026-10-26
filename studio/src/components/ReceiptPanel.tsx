import { CheckCircle2, XCircle } from "lucide-react";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { ScoreBar } from "@/components/common";
import type { ContextItem, ContextReceipt } from "@/lib/types";
import { cn } from "@/lib/utils";

export const REASON_TEXT: Record<string, string> = {
  budget: "did not fit the token budget",
  expired: "expired",
  retracted: "retracted by a human",
  superseded: "replaced by a newer version",
  scope_mismatch: "not visible to this agent's scopes",
  low_relevance: "below the relevance threshold",
  conflict_lost: "lost a conflict on the same subject",
};

function ItemRow({ item }: { item: ContextItem }) {
  const isMemory = item.kind === "memory";
  return (
    <li
      className={cn(
        "rounded-lg border p-2.5 text-xs",
        item.included ? "border-success/30 bg-success/5" : "border-destructive/25 bg-destructive/5",
      )}
      data-testid={item.included ? "receipt-included" : "receipt-excluded"}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        {item.included ? (
          <CheckCircle2 className="size-3.5 text-success" />
        ) : (
          <XCircle className="size-3.5 text-destructive" />
        )}
        <span className="font-medium">{item.subject_key ?? item.kind}</span>
        {item.scope && <Badge variant="outline">{item.scope}</Badge>}
        {!item.included && item.reason && (
          <Badge variant="destructive" title={REASON_TEXT[item.reason]}>
            {item.reason}
          </Badge>
        )}
        <span className="ml-auto flex items-center gap-1.5 text-muted-foreground tabular-nums">
          {item.tokens} tok
          <ScoreBar value={item.score.total} />
          {item.score.total.toFixed(2)}
        </span>
      </div>
      <p className="mt-1.5 text-[12px] leading-snug text-foreground/90">{item.content}</p>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[10.5px] text-muted-foreground">
        {isMemory && (
          <Link to={`/memory?focus=${item.item_id}`} className="font-mono hover:text-primary hover:underline">
            {item.item_id}
          </Link>
        )}
        {item.source && <span>source: {item.source}</span>}
        <span>
          rel {item.score.relevance.toFixed(2)} · trust {item.score.trust.toFixed(2)} · imp{" "}
          {item.score.importance.toFixed(2)} · rec {item.score.recency.toFixed(2)}
        </span>
      </div>
      {item.detail && !item.included && (
        <div className="mt-1 text-[10.5px] text-destructive/90">why: {item.detail}</div>
      )}
    </li>
  );
}

export function ReceiptPanel({ receipt }: { receipt: ContextReceipt }) {
  const included = receipt.included.filter((i) => i.kind !== "task");
  const pct = Math.min(100, (receipt.used_tokens / receipt.budget_tokens) * 100);
  return (
    <div className="space-y-3" data-testid="receipt">
      <div className="space-y-1">
        <div className="flex items-center justify-between text-xs">
          <span className="font-medium">
            Context receipt · step {receipt.step} · <span className="text-muted-foreground">{receipt.strategy}</span>
          </span>
          <span className="tabular-nums text-muted-foreground">
            {receipt.used_tokens} / {receipt.budget_tokens} tokens
          </span>
        </div>
        <div className="h-1.5 overflow-hidden rounded-full bg-muted">
          <div className="h-full bg-primary" style={{ width: `${pct}%` }} />
        </div>
        <p className="line-clamp-2 text-[11px] text-muted-foreground">query: {receipt.query}</p>
      </div>
      <section>
        <h4 className="mb-1.5 text-xs font-semibold text-success">Included ({included.length})</h4>
        <ul className="space-y-1.5">
          {included.map((i) => (
            <ItemRow key={i.item_id} item={i} />
          ))}
          {included.length === 0 && <li className="text-xs text-muted-foreground">No memories included.</li>}
        </ul>
      </section>
      <section>
        <h4 className="mb-1.5 text-xs font-semibold text-destructive">Excluded ({receipt.excluded.length})</h4>
        <ul className="space-y-1.5">
          {receipt.excluded.map((i) => (
            <ItemRow key={i.item_id + (i.reason ?? "")} item={i} />
          ))}
          {receipt.excluded.length === 0 && <li className="text-xs text-muted-foreground">Nothing excluded.</li>}
        </ul>
      </section>
    </div>
  );
}
