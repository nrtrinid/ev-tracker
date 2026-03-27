"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { AuthProvider } from "@/lib/auth-context";
import { KellyProvider } from "@/lib/kelly-context";
import { BettingPlatformProvider } from "@/lib/betting-platform-store";

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 60 * 1000, // 1 minute
            refetchOnWindowFocus: false,
            refetchOnReconnect: false,
            // When the backend is unhealthy, retries across many queries can create
            // a retry storm that amplifies outages. Individual hooks can opt back
            // into retries where it’s safe.
            retry: 0,
          },
        },
      })
  );

  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <KellyProvider>
          <BettingPlatformProvider>{children}</BettingPlatformProvider>
        </KellyProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}
