import type { Metadata } from "next";
import { ProgressView } from "@/components/progress/ProgressView";

export const metadata: Metadata = { title: "Progress" };

export default async function ProgressPage({ params }: { params: Promise<{ subjectId: string }> }) {
  const { subjectId } = await params;
  return <ProgressView subjectId={decodeURIComponent(subjectId)} />;
}
