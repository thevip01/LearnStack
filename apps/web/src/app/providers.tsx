"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { ToastProvider } from "@/components/ui/Toast";
import { ApiError } from "@/lib/api";

/**
 * Client providers mounted once at the root.
 *
 * The QueryClient is created in state so it survives re-renders but is never
 * shared between requests on the server. Defaults are deliberately conservative:
 * a short stale window keeps navigation snappy without hiding a fresh mastery
 * delta for long, and retries never fire on a deterministic 4xx.
 */
export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            gcTime: 5 * 60_000,
            refetchOnWindowFocus: false,
            retry: (failureCount, error) => {
              // A 4xx is the API's considered "no", so asking again wastes a round trip.
              if (error instanceof ApiError && error.status < 500) return false;
              return failureCount < 2;
            },
          },
          mutations: {
            retry: false,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={client}>
      <ToastProvider>{children}</ToastProvider>
    </QueryClientProvider>
  );
}
