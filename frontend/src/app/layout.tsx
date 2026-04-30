import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { ThemeProvider } from "@/components/layout/ThemeProvider";
import { DisclaimerBanner } from "@/components/layout/DisclaimerBanner";
import { Header } from "@/components/layout/Header";
import { DisclaimerModal } from "@/components/layout/DisclaimerModal";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Dr. Holmes — multi-agent diagnostic deliberation",
  description:
    "Educational research project. Six AI agents deliberate on patient cases. NOT FOR CLINICAL USE.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${geistSans.variable} ${geistMono.variable} antialiased min-h-screen flex flex-col`}>
        <ThemeProvider>
          <DisclaimerBanner />
          <Header />
          <main className="flex-1 flex flex-col">{children}</main>
          <DisclaimerModal />
        </ThemeProvider>
      </body>
    </html>
  );
}
