"use client";

import { PackageOpen } from "lucide-react";
import { EmptyState } from "@/components/ui/EmptyState";
import { lookupPanel, panelLabel } from "./PanelRegistry";
import { PanelErrorBoundary } from "./PanelErrorBoundary";
import type { PanelProps } from "./types";

/**
 * Renders one declared panel: registry lookup, then the component inside its own
 * error boundary. Nothing else: slot arrangement is the LayoutRenderer's job.
 */
export function PanelHost(props: PanelProps) {
  const { panel } = props;
  const Component = lookupPanel(panel.type);

  if (!Component) return <UnknownPanel type={panel.type} id={panel.id} />;

  return (
    <PanelErrorBoundary panelId={panel.id} panelType={panel.type}>
      <Component {...props} />
    </PanelErrorBoundary>
  );
}

/**
 * A package can only reach this by declaring a panel type this build does not
 * know: publish-time validation runs against the registry, so it means the web
 * app is older than the content. Naming the type is what makes that diagnosable.
 */
function UnknownPanel({ type, id }: { type: string; id: string }) {
  return (
    <EmptyState
      tone="pending"
      icon={<PackageOpen className="size-5" aria-hidden />}
      title="Panel type not in this build"
      description={
        <>
          The layout asks for <span className="font-mono text-ink">{type}</span> in slot{" "}
          <span className="font-mono text-ink">{id}</span>. This build of the web app has no component registered for
          it. The subject package is newer than the frontend.
        </>
      }
    />
  );
}

export { panelLabel };
