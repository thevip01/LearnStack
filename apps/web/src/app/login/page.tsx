import type { Metadata } from "next";
import { LoginView } from "@/components/auth/LoginView";

export const metadata: Metadata = { title: "Sign in" };

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const query = await searchParams;
  const raw = query.next;
  const next = Array.isArray(raw) ? raw[0] ?? null : raw ?? null;
  return <LoginView next={next} />;
}
