"use client";

import { AlertTriangle } from "lucide-react";
import { useReady } from "@/lib/queries";
import { cn } from "@/lib/utils";

/**
 * A thin status strip that stays invisible while the platform is healthy and
 * appears only when a dependency the learner will actually hit is degraded. It
 * never gates the UI (the catalogue stays readable even when the sandbox is
 * offline), so it warns rather than blocks.
 */
export function ReadinessBanner() {
  const { data, isError, isLoading } = useReady();

  if (isLoading) return null;

  const healthy = !isError && data && data.postgres && data.redis && data.sandbox !== "unavailable";
  if (healthy) return null;

  const down = isError || !data;
  const issues: string[] = [];
  if (down) {
    issues.push("the API is unreachable");
  } else {
    if (!data.postgres) issues.push("the database is down");
    if (!data.redis) issues.push("the cache is down");
    if (data.sandbox === "unavailable") issues.push("the execution sandbox is offline");
  }

  return (
    <div
      role="status"
      className={cn(
        "flex items-center gap-2 border-b px-pad py-1 text-2xs",
        down ? "border-danger/40 bg-danger/10 text-danger" : "border-warn/40 bg-warn/10 text-warn",
      )}
    >
      <AlertTriangle className="size-3.5 shrink-0" aria-hidden />
      <span>{capitalize(issues.join(", "))}. Reading works, but practice submissions may fail until service recovers.</span>
    </div>
  );
}

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}
