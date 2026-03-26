import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";
import { Toaster } from "sonner";
import { BottomNav } from "@/components/BottomNav";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "EV Tracker",
  description: "Track sports betting Expected Value",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className={inter.className}>
        <Providers>
          <BottomNav />
          <main className="min-h-screen bg-background pb-20">
            {children}
          </main>
        </Providers>
        <Toaster
          position="top-center"
          richColors
          closeButton={false}
          icons={{
            success: <></>,
            error: <></>,
            warning: <></>,
            info: <></>,
            loading: <></>,
          }}
        />
      </body>
    </html>
  );
}
