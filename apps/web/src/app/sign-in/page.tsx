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
      title="Sign in to xxx."
      description="Buyer accounts will use verified email, protected sessions, and private access to models, quotes, payments, and order tracking."
      footerLinks={[
        { label: "New here? Create an account", href: "/sign-up" },
      ]}
    >
      <SignInForm />
    </AuthShell>
  );
}
