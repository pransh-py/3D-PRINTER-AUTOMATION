import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "xxx — 3D printing in Chennai",
    template: "%s | xxx",
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
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full">{children}</body>
    </html>
  );
}
