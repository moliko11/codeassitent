import type { Metadata } from "next";
import "./globals.css";
import ThemeScript from "@/components/ThemeScript";
import { AppShellProvider } from "@/context/AppShellContext";

export const metadata: Metadata = {
  title: "Chat Template",
  description:
    "Standalone chat UI layout template, extracted from DeepTutor's conversation interface.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // System fonts via CSS variables (see globals.css :root --font-sans/-serif).
  // No next/font fetch, so it builds offline. To match DeepTutor pixel-for-
  // pixel, swap in Geist + Lora via next/font and set those variables - see README.
  return (
    <html lang="zh" suppressHydrationWarning>
      <head>
        <ThemeScript />
      </head>
      <body
        className="font-sans bg-[var(--background)] text-[var(--foreground)]"
        suppressHydrationWarning
      >
        <AppShellProvider>{children}</AppShellProvider>
      </body>
    </html>
  );
}
