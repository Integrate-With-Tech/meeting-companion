import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Korieo Companion",
  description:
    "Sign in, connect Microsoft Teams, invite the Korieo Companion bot, upload transcripts, and access AI-generated meeting notes.",
  icons: {
    icon: "/korieo-logo.svg",
    shortcut: "/korieo-logo.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
