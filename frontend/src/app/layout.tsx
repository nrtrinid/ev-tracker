import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";
import { Toaster } from "sonner";
import { TopNav } from "@/components/TopNav";

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
    <html lang="en">
      <body className={inter.className}>
        <Providers>
          <TopNav />
          {/* Main content area with binding shadow like an open notebook */}
          <main className="binding-shadow min-h-[calc(100vh-56px)]">
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
