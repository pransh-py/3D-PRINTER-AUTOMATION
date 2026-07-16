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
      description="This page checks your protected browser session with the account service."
      footerLinks={[{ label: "Back to home", href: "/" }]}
    >
      <AccountPanel />
    </AuthShell>
  );
}
