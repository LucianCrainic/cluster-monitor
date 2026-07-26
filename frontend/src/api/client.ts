import type {
  ApiErrorBody,
  AppSettings,
  Cluster,
  ClusterOverview,
  CancelJobResponse,
  Job,
  JobDetails,
  SubmitJobRequest,
  SubmitJobResponse,
} from "../types/api";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(
  /\/$/,
  "",
) ?? "/api";

export class ApiError extends Error {
  readonly status: number | null;
  readonly code: string | null;
  readonly isConnectionError: boolean;

  constructor(
    message: string,
    options: {
      status?: number | null;
      code?: string | null;
      isConnectionError?: boolean;
    } = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.status = options.status ?? null;
    this.code = options.code ?? null;
    this.isConnectionError = options.isConnectionError ?? false;
  }
}

function errorDetails(body: ApiErrorBody | null): {
  message: string | null;
  code: string | null;
} {
  if (!body) {
    return { message: null, code: null };
  }

  if (body.error) {
    return {
      message: body.error.message ?? null,
      code: body.error.code ?? null,
    };
  }

  if (typeof body.detail === "string") {
    return { message: body.detail, code: null };
  }

  if (body.detail && typeof body.detail === "object") {
    return {
      message: body.detail.message ?? null,
      code: body.detail.code ?? null,
    };
  }

  return { message: null, code: null };
}

interface ApiRequestOptions {
  signal?: AbortSignal | undefined;
  method?: "GET" | "POST" | "DELETE";
  body?: unknown;
  confirmedAction?: boolean;
}

async function request<T>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<T> {
  let response: Response;
  const { body, confirmedAction, method, signal } = options;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: {
        Accept: "application/json",
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        ...(confirmedAction
          ? { "X-Cluster-Monitor-Action": "confirmed" }
          : {}),
      },
      ...(method ? { method } : {}),
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      ...(signal ? { signal } : {}),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }

    throw new ApiError(
      "The local cluster service is not responding. Check that the backend is running.",
      { isConnectionError: true },
    );
  }

  if (!response.ok) {
    let body: ApiErrorBody | null = null;
    try {
      body = (await response.json()) as ApiErrorBody;
    } catch {
      // Some proxy and transport errors return an empty or non-JSON response.
    }
    const details = errorDetails(body);
    const connectionFailure =
      response.status === 502 ||
      response.status === 503 ||
      response.status === 504 ||
      details.code === "cluster_connection_error" ||
      details.code === "cluster_unavailable";

    throw new ApiError(
      details.message ??
        (connectionFailure
          ? "The selected cluster could not be reached."
          : `The request failed with status ${response.status}.`),
      {
        status: response.status,
        code: details.code,
        isConnectionError: connectionFailure,
      },
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export const api = {
  getClusters: (signal?: AbortSignal) =>
    request<Cluster[]>("/clusters", { signal }),
  getOverview: (clusterId: string, signal?: AbortSignal) =>
    request<ClusterOverview>(
      `/clusters/${encodeURIComponent(clusterId)}/overview`,
      { signal },
    ),
  getJobs: (clusterId: string, signal?: AbortSignal) =>
    request<Job[]>(`/clusters/${encodeURIComponent(clusterId)}/jobs`, {
      signal,
    }),
  getJob: (clusterId: string, jobId: string, signal?: AbortSignal) =>
    request<JobDetails>(
      `/clusters/${encodeURIComponent(clusterId)}/jobs/${encodeURIComponent(jobId)}`,
      { signal },
    ),
  getSettings: (signal?: AbortSignal) =>
    request<AppSettings>("/settings", { signal }),
  submitJob: (clusterId: string, submission: SubmitJobRequest) =>
    request<SubmitJobResponse>(
      `/clusters/${encodeURIComponent(clusterId)}/jobs`,
      {
        method: "POST",
        body: submission,
        confirmedAction: true,
      },
    ),
  cancelJob: (clusterId: string, jobId: string) =>
    request<CancelJobResponse>(
      `/clusters/${encodeURIComponent(clusterId)}/jobs/${encodeURIComponent(jobId)}`,
      { method: "DELETE", confirmedAction: true },
    ),
};
