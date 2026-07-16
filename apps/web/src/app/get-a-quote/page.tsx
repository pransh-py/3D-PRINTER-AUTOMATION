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
        xxx<span>.</span>
      </Link>
      <section className="form-card">
        <p className="section-kicker">QUOTE REQUEST</p>
        <h1>Upload your models.</h1>
        <p>
          Model files are stored in private, access-controlled storage and are used only to
          prepare your quote. Each upload is quarantined until our system and the owner validate
          it, so no price is ever final at the moment you submit. A browser-computed checksum
          helps bind the upload, but it is only a claim until the isolated worker verifies it.
        </p>
        <p>
          Supported formats are STL, 3MF, OBJ, STEP, and STP, up to five files per request.
        </p>
        <QuoteRequestPanel />
        <Link className="button" href="/">
          Back to home
        </Link>
      </section>
    </main>
  );
}
