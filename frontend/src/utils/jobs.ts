import type { Job } from "../types/api";
import { titleCase } from "./format";

export type JobStateGroup =
  | "running"
  | "pending"
  | "completed"
  | "failed"
  | "other";

export type JobSortKey =
  | "job_id"
  | "job_name"
  | "partition"
  | "state"
  | "elapsed_seconds"
  | "time_limit_seconds"
  | "requested_cpus"
  | "requested_gpus";

export type SortDirection = "ascending" | "descending";

export interface JobFilters {
  search: string;
  state: JobStateGroup | "all";
  partition: string;
}

export interface JobSort {
  key: JobSortKey;
  direction: SortDirection;
}

const FAILURE_STATES = new Set([
  "cancelled",
  "failed",
  "out_of_memory",
  "timeout",
]);

const COMPLETED_STATES = new Set(["completed"]);
const RUNNING_STATES = new Set(["running"]);
const PENDING_STATES = new Set(["pending", "suspended"]);

function normalizedState(state: string): string {
  return state.trim().toLowerCase().replace(/\+$/, "");
}

export function getJobStateGroup(state: string): JobStateGroup {
  const normalized = normalizedState(state);
  if (RUNNING_STATES.has(normalized)) return "running";
  if (PENDING_STATES.has(normalized)) return "pending";
  if (COMPLETED_STATES.has(normalized)) return "completed";
  if (FAILURE_STATES.has(normalized)) return "failed";
  return "other";
}

export function getJobStateLabel(state: string): string {
  return titleCase(normalizedState(state));
}

export function getJobLocation(job: Job): string {
  if (job.node_list && job.node_list.length > 0) {
    return job.node_list.join(", ");
  }
  if (job.reason) {
    return job.reason;
  }
  return "Not assigned";
}

function searchableJobText(job: Job): string {
  return [
    job.job_id,
    job.job_name,
    job.user,
    job.partition,
    job.state,
    job.reason,
    ...(job.node_list ?? []),
  ]
    .filter(Boolean)
    .join(" ")
    .toLocaleLowerCase();
}

function compareValues(left: string | number, right: string | number): number {
  if (typeof left === "number" && typeof right === "number") {
    return left - right;
  }
  return String(left).localeCompare(String(right), undefined, {
    numeric: true,
    sensitivity: "base",
  });
}

function sortValue(job: Job, key: JobSortKey): string | number {
  if (
    key === "elapsed_seconds" ||
    key === "time_limit_seconds" ||
    key === "requested_gpus"
  ) {
    return job[key] ?? -1;
  }
  return job[key];
}

export function filterAndSortJobs(
  jobs: Job[],
  filters: JobFilters,
  sort: JobSort,
): Job[] {
  const search = filters.search.trim().toLocaleLowerCase();
  const filtered = jobs.filter((job) => {
    const matchesSearch = !search || searchableJobText(job).includes(search);
    const matchesState =
      filters.state === "all" ||
      getJobStateGroup(job.state) === filters.state;
    const matchesPartition =
      filters.partition === "all" || job.partition === filters.partition;
    return matchesSearch && matchesState && matchesPartition;
  });

  return [...filtered].sort((left, right) => {
    const result = compareValues(
      sortValue(left, sort.key),
      sortValue(right, sort.key),
    );
    return sort.direction === "ascending" ? result : -result;
  });
}

export function getPartitionOptions(jobs: Job[]): string[] {
  return [...new Set(jobs.map((job) => job.partition).filter(Boolean))].sort(
    (left, right) => left.localeCompare(right),
  );
}

export function nextSort(
  current: JobSort,
  key: JobSortKey,
): JobSort {
  if (current.key !== key) {
    return { key, direction: "ascending" };
  }
  return {
    key,
    direction:
      current.direction === "ascending" ? "descending" : "ascending",
  };
}
