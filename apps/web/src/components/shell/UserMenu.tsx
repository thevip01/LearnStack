"use client";

import { ChevronDown, Shield } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useLogout, useMe } from "@/lib/queries";
import { routes } from "@/lib/routes";
import { cn } from "@/lib/utils";

/**
 * Anonymous is a first-class state: the contract removes the signup wall, so a
 * signed-out visitor sees a "Sign in" affordance rather than a redirect. A
 * signed-in admin additionally gets a link into the ingestion console.
 */
export function UserMenu() {
  const { data: user, isLoading } = useMe();
  const logout = useLogout();
  const pathname = usePathname();

  if (isLoading) return <div className="h-6 w-20 rounded skeleton-bar" aria-hidden />;

  if (!user) {
    return (
      <Link
        href={routes.login(pathname)}
        className="inline-flex h-7 items-center rounded-md border border-line bg-raised px-2.5 text-xs font-medium text-ink hover:border-accent/50"
      >
        Sign in
      </Link>
    );
  }

  return (
    <details className="group relative">
      <summary className="flex h-7 cursor-pointer list-none items-center gap-1.5 rounded-md border border-line bg-raised px-2 text-xs text-ink hover:border-accent/50 [&::-webkit-details-marker]:hidden">
        <span className="grid size-4 place-items-center rounded-full bg-accent/20 text-[0.625rem] font-semibold text-accent">
          {initial(user.display_name || user.email)}
        </span>
        <span className="max-w-[10rem] truncate">{user.display_name || user.email}</span>
        <ChevronDown className="size-3 text-faint transition-transform group-open:rotate-180" aria-hidden />
      </summary>
      <div className="absolute right-0 z-30 mt-1 w-52 rounded-panel border border-line bg-surface p-1 shadow-panel">
        <div className="truncate px-2 py-1 text-2xs text-faint" title={user.email}>
          {user.email}
        </div>
        {user.is_admin ? (
          <Link
            href={routes.adminIngestion}
            className="flex items-center gap-2 rounded px-2 py-1.5 text-xs text-muted hover:bg-raised hover:text-ink"
          >
            <Shield className="size-3.5" aria-hidden />
            Ingestion console
          </Link>
        ) : null}
        <button
          type="button"
          onClick={() => logout.mutate()}
          disabled={logout.isPending}
          className={cn(
            "w-full rounded px-2 py-1.5 text-left text-xs text-muted hover:bg-raised hover:text-ink",
            "disabled:cursor-not-allowed disabled:opacity-50",
          )}
        >
          {logout.isPending ? "Signing out…" : "Sign out"}
        </button>
      </div>
    </details>
  );
}

function initial(name: string): string {
  return name.trim().charAt(0).toUpperCase() || "?";
}
