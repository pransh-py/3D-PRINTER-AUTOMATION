import type { Metadata } from "next";
import PrintStation from "./print-station";

export const metadata: Metadata = { title: "Local print station" };

export default function PrintPage() {
  return <PrintStation />;
}
