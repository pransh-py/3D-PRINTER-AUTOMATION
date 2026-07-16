import type { Metadata } from "next";

import { AuthShell } from "@/components/auth/auth-shell";
import { ResetPasswordForm } from "@/components/auth/reset-password-form";

export const metadata: Metadata = {
  title: "Choose a new password",
};

export default function ResetPasswordPage() {
  return (
    <AuthShell
      kicker="RESET PASSWORD"
      title="Choose a new password."
      description="Choose a new password using the secure link sent to your email."
      footerLinks={[{ label: "Back to sign in", href: "/sign-in" }]}
    >
      <ResetPasswordForm />
    </AuthShell>
  );
}
