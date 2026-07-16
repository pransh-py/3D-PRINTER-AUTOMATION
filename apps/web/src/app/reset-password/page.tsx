import type { Metadata } from "next";

import { AuthShell } from "@/components/auth/auth-shell";
import styles from "@/components/auth/auth-form.module.css";

export const metadata: Metadata = {
  title: "Choose a new password",
};

export default function ResetPasswordPage() {
  return (
    <AuthShell
      kicker="RESET PASSWORD"
      title="Choose a new password."
      description="Your reset link will be checked once the secure reset service is connected."
      footerLinks={[{ label: "Back to sign in", href: "/sign-in" }]}
    >
      <form className={styles.form}>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="new-password">
            New password
          </label>
          <input
            className={styles.input}
            id="new-password"
            name="new-password"
            type="password"
            autoComplete="new-password"
            placeholder="Create a new password"
          />
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="confirm-new-password">
            Confirm new password
          </label>
          <input
            className={styles.input}
            id="confirm-new-password"
            name="confirm-new-password"
            type="password"
            autoComplete="new-password"
            placeholder="Re-enter your new password"
          />
        </div>
        <div className={styles.submitRow}>
          <button className={styles.submit} type="submit" disabled>
            Connecting secure reset service…
          </button>
          <p className={styles.disabledNote}>
            We are still connecting the secure reset service. Password resets
            will open once it is ready.
          </p>
        </div>
      </form>
    </AuthShell>
  );
}
