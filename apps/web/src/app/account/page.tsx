import type { Metadata } from "next";

import { AccountPanel } from "@/components/auth/account-panel";
import { AuthShell } from "@/components/auth/auth-shell";

export const metadata: Metadata = {
  title: "Your account",
};

export default function AccountPage() {
  return (
    <AuthShell
      kicker="YOUR ACCOUNT"
      title="Account overview."
      description="Manage your account and security."
      footerLinks={[{ label: "Back to home", href: "/" }]}
    >
      <AccountPanel />
    </AuthShell>
  );
}
