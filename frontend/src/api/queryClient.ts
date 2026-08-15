import { QueryClient } from "@tanstack/react-query";

import { ApiError } from "./client";

function shouldRetry(failureCount: number, error: Error): boolean {
  if (failureCount >= 1) {
    return false;
  }

  if (error instanceof ApiError && error.status !== null) {
    return error.status >= 500;
  }

  return true;
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        gcTime: 5 * 60 * 1000,
        staleTime: 5 * 1000,
        retry: shouldRetry,
        refetchOnReconnect: true,
        refetchOnWindowFocus: true,
        refetchIntervalInBackground: false,
      },
      mutations: {
        retry: false,
      },
    },
  });
}
