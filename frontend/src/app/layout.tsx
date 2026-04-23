import type { Metadata, Viewport } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { Toaster } from "sonner";
import { BottomNav } from "@/components/BottomNav";
import { buildThemeInitScript, THEME_BROWSER_COLORS } from "@/lib/theme";

// Font is loaded via globals.css @import — no next/font needed here
// (avoids double-loading Inter and JetBrains Mono)

export const metadata: Metadata = {
  title: "EV Tracker",
  description: "Track sports betting Expected Value",
};

export const viewport: Viewport = {
  viewportFit: "cover",
  colorScheme: "light dark",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: THEME_BROWSER_COLORS.light },
    { media: "(prefers-color-scheme: dark)", color: THEME_BROWSER_COLORS.dark },
  ],
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
          <main className="app-shell-main min-h-screen bg-background">
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
