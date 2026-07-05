import type { Metadata } from "next";
import { CatalogView } from "@/components/catalog/CatalogView";

export const metadata: Metadata = {
  title: "Subjects",
  description: "Every published subject the runtime can host.",
};

export default function SubjectsPage() {
  return <CatalogView />;
}
