import type { Metadata } from "next";

import { AuthShell } from "@/components/auth/auth-shell";
import { SignUpForm } from "@/components/auth/sign-up-form";

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
      <SignUpForm />
    </AuthShell>
  );
}
