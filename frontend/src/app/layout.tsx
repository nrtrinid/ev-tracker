import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { Toaster } from "sonner";
import { BottomNav } from "@/components/BottomNav";
import { buildThemeInitScript } from "@/lib/theme";

// Font is loaded via globals.css @import — no next/font needed here
// (avoids double-loading Inter and JetBrains Mono)

export const metadata: Metadata = {
  title: "EV Tracker",
  description: "Track sports betting Expected Value",
};

const themeInitScript = buildThemeInitScript();

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        {/* Inline theme init — runs before first paint to avoid flash */}
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
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
            error:   <></>,
            warning: <></>,
            info:    <></>,
            loading: <></>,
          }}
        />
      </body>
    </html>
  );
}
