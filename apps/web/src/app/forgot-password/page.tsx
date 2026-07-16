import type { Metadata } from "next";

import { AuthShell } from "@/components/auth/auth-shell";
import { ForgotPasswordForm } from "@/components/auth/forgot-password-form";

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
      <ForgotPasswordForm />
    </AuthShell>
  );
}
