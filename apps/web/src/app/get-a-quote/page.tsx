import type { Metadata } from "next";
import Link from "next/link";

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
        <h1>Upload is coming next.</h1>
        <p>
          We are connecting private model storage and slicer-backed estimates.
          The supported launch formats will be STL, 3MF, OBJ, STEP, and STP.
        </p>
        <Link className="button" href="/">
          Back to home
        </Link>
      </section>
    </main>
  );
}
