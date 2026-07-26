import { Link } from "react-router";

import type { Job } from "../types/api";
import {
  type JobSort,
  type JobSortKey,
  getJobLocation,
  nextSort,
} from "../utils/jobs";
import { formatDuration } from "../utils/format";
import { JobStateBadge } from "./StatusBadge";

interface JobsTableProps {
  jobs: Job[];
  sort: JobSort;
  onSort: (sort: JobSort) => void;
}

interface SortableHeaderProps {
  label: string;
  sortKey: JobSortKey;
  sort: JobSort;
  onSort: (sort: JobSort) => void;
  className?: string;
}

function SortableHeader({
  label,
  sortKey,
  sort,
  onSort,
  className,
}: SortableHeaderProps) {
  const isActive = sort.key === sortKey;
  return (
    <th
      scope="col"
      className={className}
      aria-sort={isActive ? sort.direction : "none"}
    >
      <button
        className="sort-button"
        type="button"
        onClick={() => onSort(nextSort(sort, sortKey))}
      >
        {label}
        <span className="sort-button__icon" aria-hidden="true">
          {isActive
            ? sort.direction === "ascending"
              ? "↑"
              : "↓"
            : "↕"}
        </span>
      </button>
    </th>
  );
}

export function JobsTable({ jobs, sort, onSort }: JobsTableProps) {
  return (
    <div className="table-card">
      <div className="table-scroll">
        <table className="jobs-table">
          <caption className="sr-only">
            Jobs for the selected cluster. Column headings can be used to sort
            the table.
          </caption>
          <thead>
            <tr>
              <SortableHeader
                label="Job ID"
                sortKey="job_id"
                sort={sort}
                onSort={onSort}
              />
              <SortableHeader
                label="Name"
                sortKey="job_name"
                sort={sort}
                onSort={onSort}
              />
              <SortableHeader
                label="Partition"
                sortKey="partition"
                sort={sort}
                onSort={onSort}
                className="table-column--medium"
              />
              <SortableHeader
                label="State"
                sortKey="state"
                sort={sort}
                onSort={onSort}
              />
              <SortableHeader
                label="Elapsed"
                sortKey="elapsed_seconds"
                sort={sort}
                onSort={onSort}
                className="table-column--medium"
              />
              <SortableHeader
                label="Limit"
                sortKey="time_limit_seconds"
                sort={sort}
                onSort={onSort}
                className="table-column--wide"
              />
              <SortableHeader
                label="CPUs"
                sortKey="requested_cpus"
                sort={sort}
                onSort={onSort}
                className="table-column--wide numeric"
              />
              <SortableHeader
                label="GPUs"
                sortKey="requested_gpus"
                sort={sort}
                onSort={onSort}
                className="table-column--wide numeric"
              />
              <th scope="col" className="table-column--location">
                Node / reason
              </th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => (
              <tr key={job.job_id}>
                <td>
                  <Link className="job-link" to={`/jobs/${encodeURIComponent(job.job_id)}`}>
                    {job.job_id}
                  </Link>
                </td>
                <td>
                  <span className="job-name">{job.job_name}</span>
                </td>
                <td className="table-column--medium">
                  <span className="mono-subtle">{job.partition}</span>
                </td>
                <td>
                  <JobStateBadge state={job.state} />
                </td>
                <td className="table-column--medium tabular">
                  {formatDuration(job.elapsed_seconds)}
                </td>
                <td className="table-column--wide tabular">
                  {formatDuration(job.time_limit_seconds)}
                </td>
                <td className="table-column--wide numeric tabular">
                  {job.requested_cpus}
                </td>
                <td className="table-column--wide numeric tabular">
                  {job.requested_gpus ?? "—"}
                </td>
                <td className="table-column--location">
                  <span
                    className={
                      (job.node_list?.length ?? 0) > 0
                        ? "node-list"
                        : "pending-reason"
                    }
                    title={getJobLocation(job)}
                  >
                    {getJobLocation(job)}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
