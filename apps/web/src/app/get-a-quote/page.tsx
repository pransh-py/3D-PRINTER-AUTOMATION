import type { Metadata } from "next";
import { QuoteRequestPanel } from "@/components/quotes/quote-request-panel";
import { SiteHeader } from "@/components/site-header";
import styles from "@/components/quotes/quote-request.module.css";

export const metadata: Metadata = {
  title: "Get a quote",
};

export default function GetAQuotePage() {
  return (
    <>
      <SiteHeader />
      <main id="main-content" tabIndex={-1} className={styles.page}>
        <header className={styles.intro}>
          <p className={styles.label}>YOUR FILE. YOUR NEXT PRINT.</p>
          <h1>Let’s make your model.</h1>
          <p>
            Upload, configure and review. We’ll check your models and send a
            final price before you pay.
          </p>
        </header>
        <QuoteRequestPanel />
      </main>
    </>
  );
}
