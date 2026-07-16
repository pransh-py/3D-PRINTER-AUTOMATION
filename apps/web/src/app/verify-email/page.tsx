import type { Metadata } from "next";

import { AuthShell } from "@/components/auth/auth-shell";
import { VerifyEmailPanel } from "@/components/auth/verify-email-panel";

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
      <VerifyEmailPanel />
    </AuthShell>
  );
}
