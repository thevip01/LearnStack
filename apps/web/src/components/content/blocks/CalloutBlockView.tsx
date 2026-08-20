import { AlertTriangle, Info, Lightbulb, ServerCog, ShieldAlert } from "lucide-react";
import type { ComponentType } from "react";
import { Markdown } from "@/components/content/Markdown";
import type { CalloutBlock } from "@/lib/types";
import { cn } from "@/lib/utils";

const VARIANTS: Record<
  CalloutBlock["variant"],
  { border: string; icon: ComponentType<{ className?: string }>; label: string }
> = {
  note: { border: "border-line bg-raised/50", icon: Info, label: "Note" },
  tip: { border: "border-info/40 bg-info/5", icon: Lightbulb, label: "Tip" },
  warning: { border: "border-warn/40 bg-warn/5", icon: AlertTriangle, label: "Warning" },
  danger: { border: "border-danger/40 bg-danger/5", icon: ShieldAlert, label: "Danger" },
  production: { border: "border-accent/40 bg-accent/5", icon: ServerCog, label: "In production" },
};

export function CalloutBlockView({ block }: { block: CalloutBlock }) {
  const variant = VARIANTS[block.variant] ?? VARIANTS.note;
  const Icon = variant.icon;
  return (
    <aside className={cn("rounded-panel border p-pad", variant.border)}>
      <div className="mb-1 flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wide text-muted">
        <Icon className="size-3.5" aria-hidden />
        {block.title ?? variant.label}
      </div>
      <Markdown>{block.md}</Markdown>
    </aside>
  );
}
