import type { Metadata } from "next";

import { AuthShell } from "@/components/auth/auth-shell";
import styles from "@/components/auth/auth-form.module.css";

export const metadata: Metadata = {
  title: "Sign in",
};

export default function SignInPage() {
  return (
    <AuthShell
      kicker="YOUR ACCOUNT"
      title="Sign in to xxx."
      description="Buyer accounts will use verified email, protected sessions, and private access to models, quotes, payments, and order tracking."
      footerLinks={[
        { label: "Forgot your password?", href: "/forgot-password" },
        { label: "New here? Create an account", href: "/sign-up" },
      ]}
    >
      <form className={styles.form}>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="email">
            Email
          </label>
          <input
            className={styles.input}
            id="email"
            name="email"
            type="email"
            autoComplete="email"
            placeholder="you@example.com"
          />
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="password">
            Password
          </label>
          <input
            className={styles.input}
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            placeholder="Your password"
          />
        </div>
        <div className={styles.submitRow}>
          <button className={styles.submit} type="submit" disabled>
            Connecting secure sign-in…
          </button>
          <p className={styles.disabledNote}>
            We are still connecting the secure account service. Sign-in will
            open once it is ready.
          </p>
        </div>
      </form>
    </AuthShell>
  );
}
