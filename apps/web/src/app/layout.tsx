import type { Metadata } from "next";
import "./globals.css";
import { AppearanceSwitch } from "@/components/appearance-switch";

export const metadata: Metadata = {
  title: {
    default: "PrintFlow 3D | Your file. Made real.",
    template: "%s | PrintFlow 3D",
  },
  description:
    "3D printing in Chennai. Explore PLA and PETG, upload your model, and configure your next print with PrintFlow 3D.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      data-theme="light"
      data-scroll-behavior="smooth"
      className="h-full antialiased"
    >
      <body className="min-h-full">
        {children}
        <AppearanceSwitch />
      </body>
    </html>
  );
}
