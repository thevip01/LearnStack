import type { Metadata } from "next";
import { IngestionView } from "@/components/admin/IngestionView";

export const metadata: Metadata = { title: "Ingestion" };

export default function IngestionPage() {
  return <IngestionView />;
}
