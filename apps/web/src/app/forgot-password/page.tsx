import type { Metadata } from "next";

import { AuthShell } from "@/components/auth/auth-shell";
import styles from "@/components/auth/auth-form.module.css";

export const metadata: Metadata = {
  title: "Reset your password",
};

export default function ForgotPasswordPage() {
  return (
    <AuthShell
      kicker="RESET PASSWORD"
      title="Forgot your password?"
      description="Enter the email on your account. If it matches an existing account, we will send reset instructions."
      footerLinks={[{ label: "Back to sign in", href: "/sign-in" }]}
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
        <div className={styles.submitRow}>
          <button className={styles.submit} type="submit" disabled>
            Connecting secure account service…
          </button>
          <p className={styles.disabledNote}>
            We are still connecting the secure account service. Password
            resets will open once it is ready.
          </p>
        </div>
      </form>
    </AuthShell>
  );
}
