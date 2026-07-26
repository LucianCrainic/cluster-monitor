import type { components } from "./api.generated";

type Schemas = components["schemas"];

export type AccountingInfo = Schemas["AccountingInfo"];
export type AppSettings = Schemas["ClientSettings"];
export type Cluster = Schemas["Cluster"];
export type ClusterOverview = Schemas["ClusterOverview"];
export type ConnectionStatus = Schemas["ConnectionStatus"];
export type Job = Schemas["Job"];
export type JobDetails = Schemas["JobDetails"];
export type JobState = Schemas["JobState"];
export type RefreshSettings = Schemas["RefreshSettings"];

export interface SubmitJobRequest {
  job_name: string;
  script: string;
  partition: string | null;
  nodes: number;
  cpus_per_task: number;
  memory_mb: number | null;
  time_limit_minutes: number;
  gpus_per_node: number;
}

export interface SubmitJobResponse {
  cluster_id: string;
  job_id: string;
  submitted_at: string;
  scheduler_cluster: string | null;
  status: "submitted";
}

export interface CancelJobResponse {
  cluster_id: string;
  job_id: string;
  requested_at: string;
  status: "cancellation_requested";
}

type FrameworkErrorBody = {
  error?: undefined;
  detail?: string | { code?: string; message?: string };
};

export type ApiErrorBody =
  | Schemas["ApiErrorResponse"]
  | FrameworkErrorBody;
