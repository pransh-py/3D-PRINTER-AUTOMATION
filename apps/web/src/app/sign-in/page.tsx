import type { Metadata } from "next";

import { AuthShell } from "@/components/auth/auth-shell";
import { SignInForm } from "@/components/auth/sign-in-form";

export const metadata: Metadata = {
  title: "Sign in",
};

export default function SignInPage() {
  return (
    <AuthShell
      kicker="YOUR ACCOUNT"
      title="Welcome back"
      description="Sign in to review your quotations, manage private model files and follow your orders."
      footerLinks={[
        { label: "New here? Create an account", href: "/sign-up" },
      ]}
    >
      <SignInForm />
    </AuthShell>
  );
}
