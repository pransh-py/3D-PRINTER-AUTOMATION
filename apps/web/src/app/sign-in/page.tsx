import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Sign in",
};

export default function SignInPage() {
  return (
    <main className="form-shell">
      <Link className="wordmark" href="/">
        xxx<span>.</span>
      </Link>
      <section className="form-card">
        <p className="section-kicker">YOUR ACCOUNT</p>
        <h1>Sign-in is being secured.</h1>
        <p>
          Buyer accounts will use verified email, protected sessions, and
          private access to models, quotes, payments, and order tracking.
        </p>
        <Link className="button" href="/">
          Back to home
        </Link>
      </section>
    </main>
  );
}
