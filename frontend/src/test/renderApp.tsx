import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";

import { App } from "../App";
import {
  mockCluster,
  mockJobDetails,
  mockJobs,
  mockOverview,
  mockSettings,
} from "./fixtures";

type ApiOverrides = Partial<{
  clusters: Response | Promise<Response>;
  overview: Response | Promise<Response>;
  jobs: Response | Promise<Response>;
  job: Response | Promise<Response>;
  submitJob: Response | Promise<Response>;
  cancelJob: Response | Promise<Response>;
  settings: Response | Promise<Response>;
}>;

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function responseFor(
  value: Response | Promise<Response> | undefined,
  fallback: unknown,
  fallbackStatus = 200,
): Promise<Response> {
  return Promise.resolve(value ?? jsonResponse(fallback, fallbackStatus));
}

export function installApiMock(overrides: ApiOverrides = {}) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const path = new URL(url, "http://localhost").pathname;
    const method = init?.method ?? "GET";

    if (path === "/api/settings") {
      return responseFor(overrides.settings, mockSettings);
    }
    if (path === "/api/clusters") {
      return responseFor(overrides.clusters, [mockCluster]);
    }
    if (path.endsWith("/overview")) {
      return responseFor(overrides.overview, mockOverview);
    }
    if (path.endsWith("/jobs") && method === "POST") {
      return responseFor(overrides.submitJob, {
        cluster_id: mockCluster.id,
        job_id: "20001",
        submitted_at: "2026-07-26T11:00:00Z",
        scheduler_cluster: null,
        status: "submitted",
      }, 201);
    }
    if (path.includes("/jobs/") && method === "DELETE") {
      const jobId = decodeURIComponent(path.split("/").at(-1) ?? "");
      return responseFor(overrides.cancelJob, {
        cluster_id: mockCluster.id,
        job_id: jobId,
        requested_at: "2026-07-26T11:05:00Z",
        status: "cancellation_requested",
      });
    }
    if (path.endsWith("/jobs")) {
      return responseFor(overrides.jobs, mockJobs);
    }
    if (path.includes("/jobs/")) {
      return responseFor(overrides.job, mockJobDetails);
    }

    return Promise.resolve(
      jsonResponse(
        { error: { code: "not_found", message: "Not found" } },
        404,
      ),
    );
  });

  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

export function renderApp(route = "/") {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        staleTime: Number.POSITIVE_INFINITY,
      },
    },
  });

  const result = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );

  return { ...result, queryClient };
}
