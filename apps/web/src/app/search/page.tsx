import type { Metadata } from "next";
import { SearchView } from "@/components/search/SearchView";

export const metadata: Metadata = { title: "Search" };

export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const query = await searchParams;
  const raw = query.q;
  const initial = Array.isArray(raw) ? raw[0] ?? "" : raw ?? "";
  return <SearchView initialQuery={initial} />;
}
