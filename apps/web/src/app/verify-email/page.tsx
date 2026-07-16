import type { Metadata } from "next";

import { AuthShell } from "@/components/auth/auth-shell";
import styles from "@/components/auth/auth-form.module.css";

export const metadata: Metadata = {
  title: "Verify your email",
};

export default function VerifyEmailPage() {
  return (
    <AuthShell
      kicker="CHECK YOUR INBOX"
      title="Verify your email."
      description="If that email matches an xxx account, a verification link is on its way. Open it to activate your account and start requesting quotes."
      footerLinks={[
        { label: "Back to sign in", href: "/sign-in" },
        { label: "Need an account? Sign up", href: "/sign-up" },
      ]}
    >
      <div className={styles.submitRow}>
        <button className={styles.submit} type="button" disabled>
          Connecting secure account service…
        </button>
        <p className={styles.disabledNote}>
          We are still connecting the secure account service. Resending a
          verification email will open once it is ready.
        </p>
      </div>
    </AuthShell>
  );
}
