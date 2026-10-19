import type { Metadata } from "next";
import "./globals.css";
import { AppearanceSwitch } from "@/components/appearance-switch";

export const metadata: Metadata = {
  title: {
    default: "PrintFlow 3D | Private model quotation and order tracking",
    template: "%s | PrintFlow 3D",
  },
  description:
    "Upload your model, receive a reviewed quote, and get it 3D printed in Chennai.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" data-scroll-behavior="smooth" className="h-full antialiased">
      <body className="min-h-full">{children}<AppearanceSwitch /></body>
    </html>
  );
}
