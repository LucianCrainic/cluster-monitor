import { useMemo, useState } from "react";
import { Link } from "react-router";

import { useJobsQuery, useRefreshSettings } from "../api/queries";
import { JobsTable } from "../components/JobsTable";
import { EmptyState, ErrorState, LoadingState } from "../components/PageState";
import { RefreshButton } from "../components/RefreshButton";
import { useCluster } from "../context/useCluster";
import {
  type JobFilters,
  type JobSort,
  type JobStateGroup,
  filterAndSortJobs,
  getPartitionOptions,
} from "../utils/jobs";

const INITIAL_FILTERS: JobFilters = {
  search: "",
  state: "all",
  partition: "all",
};

const INITIAL_SORT: JobSort = {
  key: "job_id",
  direction: "descending",
};

export function JobsPage() {
  const { selectedCluster, selectedClusterId } = useCluster();
  const refresh = useRefreshSettings();
  const jobsQuery = useJobsQuery(selectedClusterId);
  const [filters, setFilters] = useState<JobFilters>(INITIAL_FILTERS);
  const [sort, setSort] = useState<JobSort>(INITIAL_SORT);
  const actionsEnabled = selectedCluster?.job_actions_enabled === true;

  const jobs = useMemo(() => jobsQuery.data ?? [], [jobsQuery.data]);
  const partitions = useMemo(() => getPartitionOptions(jobs), [jobs]);
  const visibleJobs = useMemo(
    () => filterAndSortJobs(jobs, filters, sort),
    [filters, jobs, sort],
  );
  const hasFilters =
    filters.search !== "" ||
    filters.state !== "all" ||
    filters.partition !== "all";

  function clearFilters() {
    setFilters(INITIAL_FILTERS);
  }

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <p className="page-header__eyebrow">Scheduler queue</p>
          <h1>Jobs</h1>
          <p>
            Running and pending work on{" "}
            <strong>{selectedCluster?.name ?? "the selected cluster"}</strong>.
          </p>
        </div>
        <div className="page-header__actions">
          {actionsEnabled ? (
            <Link className="button button--primary" to="/jobs/submit">
              Submit job
            </Link>
          ) : (
            <span className="job-actions-disabled" role="note">
              Job actions are disabled for this cluster.
            </span>
          )}
          {jobsQuery.data ? (
            <RefreshButton
              isRefreshing={jobsQuery.isFetching}
              onRefresh={() => {
                void jobsQuery.refetch();
              }}
            />
          ) : null}
        </div>
      </header>

      {jobsQuery.isLoading ? (
        <LoadingState label="Loading jobs…" variant="table" />
      ) : jobsQuery.error ? (
        <ErrorState
          error={jobsQuery.error}
          onRetry={() => {
            void jobsQuery.refetch();
          }}
        />
      ) : jobs.length === 0 ? (
        <EmptyState
          title="No active jobs"
          description="There are no running or pending jobs for the configured user."
        />
      ) : (
        <>
          <section className="filters" aria-label="Job filters">
            <div className="field field--search">
              <label htmlFor="job-search">Search jobs</label>
              <div className="search-input">
                <span aria-hidden="true">⌕</span>
                <input
                  id="job-search"
                  type="search"
                  value={filters.search}
                  placeholder="ID, name, node, or reason"
                  onChange={(event) =>
                    setFilters((current) => ({
                      ...current,
                      search: event.target.value,
                    }))
                  }
                />
              </div>
            </div>
            <div className="field">
              <label htmlFor="job-state-filter">State</label>
              <select
                id="job-state-filter"
                value={filters.state}
                onChange={(event) =>
                  setFilters((current) => ({
                    ...current,
                    state: event.target.value as JobStateGroup | "all",
                  }))
                }
              >
                <option value="all">All states</option>
                <option value="running">Running</option>
                <option value="pending">Pending</option>
                <option value="completed">Completed</option>
                <option value="failed">Failed</option>
                <option value="other">Other</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="job-partition-filter">Partition</label>
              <select
                id="job-partition-filter"
                value={filters.partition}
                onChange={(event) =>
                  setFilters((current) => ({
                    ...current,
                    partition: event.target.value,
                  }))
                }
              >
                <option value="all">All partitions</option>
                {partitions.map((partition) => (
                  <option key={partition} value={partition}>
                    {partition}
                  </option>
                ))}
              </select>
            </div>
            <button
              className="button button--ghost filters__clear"
              type="button"
              onClick={clearFilters}
              disabled={!hasFilters}
            >
              Clear filters
            </button>
          </section>

          <div className="results-summary" role="status" aria-live="polite">
            <span>
              Showing <strong>{visibleJobs.length}</strong> of{" "}
              <strong>{jobs.length}</strong> jobs
            </span>
            <span>
              Updates automatically every {refresh.jobs_seconds}{" "}
              {refresh.jobs_seconds === 1 ? "second" : "seconds"}
            </span>
          </div>

          {visibleJobs.length === 0 ? (
            <EmptyState
              title="No jobs match"
              description="Try a different search, state, or partition."
              action={
                <button
                  className="button button--secondary"
                  type="button"
                  onClick={clearFilters}
                >
                  Reset job filters
                </button>
              }
            />
          ) : (
            <JobsTable jobs={visibleJobs} sort={sort} onSort={setSort} />
          )}
        </>
      )}
    </div>
  );
}
