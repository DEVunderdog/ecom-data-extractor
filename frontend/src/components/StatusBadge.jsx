import React from "react";
import { Badge } from "@/components/ui/badge";

const MAP = {
  queued: "border-amber-500/30 bg-amber-500/10 text-amber-300",
  running: "border-sky-500/30 bg-sky-500/10 text-sky-300",
  completed: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  failed: "border-rose-500/30 bg-rose-500/10 text-rose-300",
};

export default function StatusBadge({ status }) {
  const cls = MAP[status] || "border-neutral-700 bg-neutral-800/60 text-neutral-300";
  return (
    <Badge
      variant="outline"
      className={`rounded-full px-2.5 py-0.5 text-[11px] font-medium uppercase tracking-wider ${cls}`}
      data-testid={`status-badge-${status}`}
    >
      <span className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-current" />
      {status}
    </Badge>
  );
}
