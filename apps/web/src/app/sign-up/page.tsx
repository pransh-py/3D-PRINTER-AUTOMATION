import type { Metadata } from "next";

import { AuthShell } from "@/components/auth/auth-shell";
import styles from "@/components/auth/auth-form.module.css";

export const metadata: Metadata = {
  title: "Create an account",
};

export default function SignUpPage() {
  return (
    <AuthShell
      kicker="CREATE AN ACCOUNT"
      title="Join xxx."
      description="Buyer accounts get private model storage, reviewed quotes, UPI payment tracking, and order updates from queue to delivery."
      footerLinks={[
        { label: "Already have an account? Sign in", href: "/sign-in" },
      ]}
    >
      <form className={styles.form}>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="name">
            Display name
          </label>
          <input
            className={styles.input}
            id="name"
            name="name"
            type="text"
            autoComplete="name"
            placeholder="Your name"
          />
        </div>
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
            autoComplete="new-password"
            placeholder="Create a password"
          />
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="password-confirmation">
            Confirm password
          </label>
          <input
            className={styles.input}
            id="password-confirmation"
            name="password-confirmation"
            type="password"
            autoComplete="new-password"
            placeholder="Re-enter your password"
          />
        </div>
        <div className={styles.checkboxField}>
          <input
            className={styles.checkboxInput}
            id="terms"
            name="terms"
            type="checkbox"
            required
          />
          <label className={styles.checkboxLabel} htmlFor="terms">
            I agree to the xxx Terms of Service and Privacy Policy.
          </label>
        </div>
        <div className={styles.submitRow}>
          <button className={styles.submit} type="submit" disabled>
            Connecting secure account service…
          </button>
          <p className={styles.disabledNote}>
            We are still connecting the secure account service. Account
            creation will open once it is ready.
          </p>
        </div>
      </form>
    </AuthShell>
  );
}
