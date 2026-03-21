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
