import type { Metadata } from "next";
import { WorkflowPanel } from "@/components/workflow/workflow-panel";

export const metadata: Metadata = { title: "Owner dashboard" };
export default function OperationsPage() {
  return <WorkflowPanel owner />;
}
