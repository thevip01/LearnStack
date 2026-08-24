import type { Metadata } from "next";
import { SubjectOverview } from "@/components/subject/SubjectOverview";

export const metadata: Metadata = { title: "Subject" };

/**
 * Params are a promise in Next 15, and the id arrives percent-encoded because
 * `routes.subject()` encodes it.
 */
export default async function SubjectPage({ params }: { params: Promise<{ subjectId: string }> }) {
  const { subjectId } = await params;
  return <SubjectOverview subjectId={decodeURIComponent(subjectId)} />;
}
