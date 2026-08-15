import type {
  ApiErrorBody,
  AppSettings,
  Cluster,
  ClusterOverview,
  ClusterTopology,
  CancelJobResponse,
  Job,
  JobDetails,
  JobLogEvent,
  RemoteDirectory,
  RemoteDirectoryRequest,
  RemoteFilePreview,
  RemoteFilePreviewRequest,
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

function connectionError(error: unknown): never {
  if (error instanceof DOMException && error.name === "AbortError") {
    throw error;
  }
  throw new ApiError(
    "The local cluster service is not responding. Check that the backend is running.",
    { isConnectionError: true },
  );
}

async function responseError(response: Response): Promise<ApiError> {
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
  return new ApiError(
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
    connectionError(error);
  }

  if (!response.ok) {
    throw await responseError(response);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export async function* streamJobLogs(
  clusterId: string,
  jobId: string,
  signal: AbortSignal,
): AsyncGenerator<JobLogEvent> {
  let response: Response;
  try {
    response = await fetch(
      `${API_BASE_URL}/clusters/${encodeURIComponent(clusterId)}/jobs/${encodeURIComponent(jobId)}/logs/stream`,
      {
        headers: { Accept: "text/event-stream" },
        signal,
      },
    );
  } catch (error) {
    connectionError(error);
  }
  if (!response.ok) {
    throw await responseError(response);
  }
  if (!response.headers.get("Content-Type")?.includes("text/event-stream")) {
    throw new ApiError("The backend returned an invalid job-log stream.", {
      status: response.status,
    });
  }
  if (!response.body) {
    throw new ApiError("The backend returned an empty job-log stream.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done }).replaceAll("\r\n", "\n");
      let boundary = buffer.indexOf("\n\n");
      while (boundary >= 0) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const event = parseJobLogEventFrame(frame);
        if (event) {
          yield event;
        }
        boundary = buffer.indexOf("\n\n");
      }
      if (done) {
        break;
      }
    }
    const finalEvent = parseJobLogEventFrame(buffer);
    if (finalEvent) {
      yield finalEvent;
    }
  } finally {
    reader.releaseLock();
  }
}

export function parseJobLogEventFrame(frame: string): JobLogEvent | null {
  if (!frame || frame.startsWith(":")) {
    return null;
  }
  const data = frame
    .split("\n")
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart())
    .join("\n");
  if (!data) {
    return null;
  }
  let value: unknown;
  try {
    value = JSON.parse(data);
  } catch {
    throw new ApiError("The backend sent a malformed job-log event.");
  }
  if (!isJobLogEvent(value)) {
    throw new ApiError("The backend sent an unsupported job-log event.");
  }
  return value;
}

function isJobLogEvent(value: unknown): value is JobLogEvent {
  if (!value || typeof value !== "object" || !("type" in value)) {
    return false;
  }
  const event = value as Record<string, unknown>;
  if (event.type === "metadata") {
    return (
      typeof event.job_id === "string" &&
      Array.isArray(event.sources) &&
      event.sources.every((source) =>
        ["stdout", "stderr", "combined"].includes(String(source)),
      ) &&
      typeof event.initial_lines === "number"
    );
  }
  if (event.type === "status") {
    return (
      ["waiting", "live", "finalizing"].includes(String(event.status)) &&
      typeof event.message === "string"
    );
  }
  if (event.type === "chunk") {
    return (
      ["stdout", "stderr", "combined"].includes(String(event.source)) &&
      typeof event.sequence === "number" &&
      typeof event.text === "string"
    );
  }
  if (event.type === "error") {
    return (
      typeof event.code === "string" &&
      typeof event.message === "string" &&
      typeof event.retryable === "boolean"
    );
  }
  return (
    event.type === "complete" &&
    ["snapshot_complete", "job_finished", "unavailable"].includes(
      String(event.reason),
    )
  );
}

export const api = {
  getClusters: (signal?: AbortSignal) =>
    request<Cluster[]>("/clusters", { signal }),
  getOverview: (clusterId: string, signal?: AbortSignal) =>
    request<ClusterOverview>(
      `/clusters/${encodeURIComponent(clusterId)}/overview`,
      { signal },
    ),
  getTopology: (clusterId: string, signal?: AbortSignal) =>
    request<ClusterTopology>(
      `/clusters/${encodeURIComponent(clusterId)}/topology`,
      { signal },
    ),
  listRemoteDirectory: (
    clusterId: string,
    directory: RemoteDirectoryRequest,
    signal?: AbortSignal,
  ) =>
    request<RemoteDirectory>(
      `/clusters/${encodeURIComponent(clusterId)}/files/list`,
      { method: "POST", body: directory, signal },
    ),
  previewRemoteFile: (
    clusterId: string,
    preview: RemoteFilePreviewRequest,
    signal?: AbortSignal,
  ) =>
    request<RemoteFilePreview>(
      `/clusters/${encodeURIComponent(clusterId)}/files/preview`,
      { method: "POST", body: preview, signal },
    ),
  getJobs: (clusterId: string, signal?: AbortSignal) =>
    request<Job[]>(`/clusters/${encodeURIComponent(clusterId)}/jobs`, {
      signal,
    }),
  getHistory: (clusterId: string, signal?: AbortSignal) =>
    request<Job[]>(
      `/clusters/${encodeURIComponent(clusterId)}/history?limit=100`,
      { signal },
    ),
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
  streamJobLogs,
};
