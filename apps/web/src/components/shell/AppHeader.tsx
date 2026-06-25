"use client";

import { GraduationCap, Search } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import { routes } from "@/lib/routes";
import { cn } from "@/lib/utils";
import { ReadinessBanner } from "./ReadinessBanner";
import { UserMenu } from "./UserMenu";

/**
 * The one piece of chrome above every route: brand, catalogue link, global
 * search and the account menu. It carries no subject knowledge: a subject's
 * own toolbar (title, mode switcher, progress) lives inside the runtime.
 */
export function AppHeader() {
  const pathname = usePathname();
  const onSubjects = pathname.startsWith("/subjects");

  return (
    <header className="shrink-0">
      <ReadinessBanner />
      <div className="flex h-10 items-center gap-3 border-b border-line bg-surface px-pad">
        <Link href={routes.home} className="flex items-center gap-1.5 text-sm font-semibold text-ink">
          <GraduationCap className="size-4 text-accent" aria-hidden />
          LearnOS
        </Link>
        <Link href={routes.subjects} className={cn("text-xs hover:text-ink", onSubjects ? "text-ink" : "text-muted")}>
          Subjects
        </Link>
        <HeaderSearch />
        <UserMenu />
      </div>
    </header>
  );
}

function HeaderSearch() {
  const router = useRouter();
  const [q, setQ] = useState("");

  return (
    <form
      className="ml-auto hidden sm:block"
      onSubmit={(event) => {
        event.preventDefault();
        const query = q.trim();
        if (query.length > 1) router.push(routes.search(query));
      }}
    >
      <div className="relative">
        <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-faint" aria-hidden />
        <input
          value={q}
          onChange={(event) => setQ(event.target.value)}
          placeholder="Search concepts, practice…"
          aria-label="Search the catalogue"
          className="h-7 w-64 rounded-md border border-line bg-canvas pl-7 pr-2 text-xs text-ink placeholder:text-faint focus:border-accent/50"
        />
      </div>
    </form>
  );
}
