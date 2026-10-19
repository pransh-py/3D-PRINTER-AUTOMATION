import type { Metadata } from "next";
import Link from "next/link";

import { QuoteRequestPanel } from "@/components/quotes/quote-request-panel";

export const metadata: Metadata = {
  title: "Get a quote",
};

export default function GetAQuotePage() {
  return (
    <main className="form-shell">
      <Link className="wordmark" href="/">
        PrintFlow <span>3D</span>
      </Link>
      <section className="form-card">
        <p className="section-kicker">QUOTE REQUEST</p>
        <h1>Start with your model</h1>
        <p>
          Upload your model, choose a material and print settings, then request
          a quotation. Your files stay private. Review the owner-confirmed price
          before you pay.
        </p>
        <QuoteRequestPanel />
        <Link className="button" href="/">
          Back to home
        </Link>
      </section>
    </main>
  );
}
