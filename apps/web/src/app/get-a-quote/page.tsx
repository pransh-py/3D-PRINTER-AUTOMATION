import type { Metadata } from "next";
import { QuoteRequestPanel } from "@/components/quotes/quote-request-panel";
import { SiteHeader } from "@/components/site-header";
import styles from "@/app/print/station.module.css";

export const metadata: Metadata = {
  title: "Get a quote",
};

export default function GetAQuotePage() {
  const presentation = process.env.PRINTFLOW_PRESENTATION_MODE === "1";
  return (
    <div className={styles.shell}>
      <SiteHeader presentation={presentation} />
      <main id="main-content" tabIndex={-1} className={styles.page}>
        <header className={styles.title}>
          <div>
            <h1>Make it your own.</h1>
            <p>Your model, your material, your next print.</p>
          </div>
        </header>
        <QuoteRequestPanel presentation={presentation} />
      </main>
    </div>
  );
}
