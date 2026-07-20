import type { Metadata } from "next";
import { CompareView } from "@/components/compare/CompareView";

export const metadata: Metadata = { title: "Compare" };

export default async function ComparePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const query = await searchParams;
  const raw = query.ids;
  const joined = Array.isArray(raw) ? raw.join(",") : raw ?? "";
  const ids = joined
    .split(",")
    .map((id) => id.trim())
    .filter(Boolean);

  return <CompareView ids={ids} />;
}
