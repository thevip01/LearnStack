"use client";

import { AlertTriangle } from "lucide-react";
import { useReady } from "@/lib/queries";
import { readinessIssues } from "@/lib/readiness";
import { cn } from "@/lib/utils";

/**
 * A thin status strip that stays invisible while the platform is healthy and
 * appears only when a dependency the learner will actually hit is degraded. It
 * never gates the UI (the catalogue stays readable even when the sandbox is
 * offline), so it warns rather than blocks.
 *
 * Which dependencies count, and what each one means for the learner, is decided by
 * `readinessIssues` in `lib/readiness.ts`. Two of those rules exist because this
 * banner got it wrong: it warned about a cache the learner cannot feel, and it
 * blamed practice submissions for outages that do not touch them.
 */
export function ReadinessBanner() {
  const { data, isError, isLoading } = useReady();

  if (isLoading) return null;

  const { issues, severe } = readinessIssues(data, isError);
  if (issues.length === 0) return null;

  return (
    <div
      role="status"
      className={cn(
        "flex items-center gap-2 border-b px-pad py-1 text-2xs",
        severe ? "border-danger/40 bg-danger/10 text-danger" : "border-warn/40 bg-warn/10 text-warn",
      )}
    >
      <AlertTriangle className="size-3.5 shrink-0" aria-hidden />
      <span>{issues.join(" ")}</span>
    </div>
  );
}
