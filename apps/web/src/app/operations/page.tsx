import type { Metadata } from "next";
import { WorkflowPanel } from "@/components/workflow/workflow-panel";

export const metadata: Metadata = { title: "Business operations" };
export default function OperationsPage() {
  return <WorkflowPanel owner />;
}
