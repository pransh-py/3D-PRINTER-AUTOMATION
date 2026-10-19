import type { Metadata } from "next";
import { WorkflowPanel } from "@/components/workflow/workflow-panel";

export const metadata: Metadata = { title: "Your quotes and orders" };
export default function OrdersPage() {
  return <WorkflowPanel />;
}
