"use client";

import { Lock } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { loginHref } from "@/lib/authGate";
import { useMe } from "@/lib/queries";
import { cn } from "@/lib/utils";

/**
 * Whether the person looking at this can finish what the panel is offering.
 *
 * `useMe()` resolves to null for a visitor rather than throwing, so `locked` is a
 * real answer and not an error state. While it is still resolving the answer is
 * "not locked", on purpose: flashing a lock at someone who is signed in is worse
 * than the half second where a signed-out visitor sees a live button, and if they
 * beat the query and press it, the 401 redirect still lands them in the right
 * place.
 */
export function useSessionGate(): { locked: boolean; resolving: boolean; href: string } {
  const { data: user, isLoading } = useMe();
  const pathname = usePathname();
  return { locked: !isLoading && !user, resolving: isLoading, href: loginHref(pathname ?? "/") };
}

const SIZES = { xs: "h-6 px-2 text-2xs gap-1", sm: "h-7 px-2.5 text-xs gap-1.5" } as const;

/**
 * Stands in for the action a signed-out visitor cannot take.
 *
 * Deliberately not a disabled button. A disabled control says "not now" and gives
 * no way forward; this says what is missing and is itself the way to fix it. The
 * warn tone rather than the accent tone keeps it from competing with the real
 * primary action on panels where both can appear.
 */
export function SignInToAct({
  action,
  size = "xs",
  className,
}: {
  /** Verb phrase completing "Sign in to …", e.g. "submit" or "take a hint". */
  action: string;
  size?: keyof typeof SIZES;
  className?: string;
}) {
  const { href } = useSessionGate();
  return (
    <Link
      href={href}
      title={`${action[0]?.toUpperCase()}${action.slice(1)} is recorded against your mastery, so this one needs an account. Reading stays open.`}
      className={cn(
        "inline-flex items-center justify-center whitespace-nowrap rounded-md border border-warn/40 bg-warn/10 font-medium text-warn transition-colors hover:bg-warn/20",
        SIZES[size],
        className,
      )}
    >
      <Lock className="size-3" aria-hidden />
      Sign in to {action}
    </Link>
  );
}

/**
 * The same fact stated on a listing rather than on a control: this way in has
 * something in it you will be asked to sign in for.
 */
export function LockedHint({ label = "Sign in to attempt" }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-1 text-2xs text-warn" title="Reading is open. Recording an attempt needs an account.">
      <Lock className="size-3" aria-hidden />
      {label}
    </span>
  );
}
