import type { Metadata } from "next";
import { WorkflowPanel } from "@/components/workflow/workflow-panel";

export const metadata: Metadata = { title: "Your dashboard" };
export default function OrdersPage() {
  return <WorkflowPanel />;
}
