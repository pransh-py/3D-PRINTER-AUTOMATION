import type { Metadata } from "next";
import { WorkflowPanel } from "@/components/workflow/workflow-panel";
import { PresentationWorkspace } from "@/components/workflow/presentation-workspace";

export const metadata: Metadata = { title: "Owner dashboard" };
export default function OperationsPage() {
  return process.env.PRINTFLOW_PRESENTATION_MODE === "1" ? <PresentationWorkspace owner /> : <WorkflowPanel owner />;
}
