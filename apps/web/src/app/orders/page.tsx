import type { Metadata } from "next";
import { WorkflowPanel } from "@/components/workflow/workflow-panel";
import { PresentationWorkspace } from "@/components/workflow/presentation-workspace";

export const metadata: Metadata = { title: "Your dashboard" };
export default function OrdersPage() {
  return process.env.PRINTFLOW_PRESENTATION_MODE === "1" ? <PresentationWorkspace /> : <WorkflowPanel />;
}
