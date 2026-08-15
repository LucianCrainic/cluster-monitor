import { useMemo, useState } from "react";

import { useHistoryQuery, useRefreshSettings } from "../api/queries";
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
  key: "submit_time",
  direction: "descending",
};

export function HistoryPage() {
  const { selectedCluster, selectedClusterId } = useCluster();
  const refresh = useRefreshSettings();
  const historyQuery = useHistoryQuery(selectedClusterId);
  const [filters, setFilters] = useState<JobFilters>(INITIAL_FILTERS);
  const [sort, setSort] = useState<JobSort>(INITIAL_SORT);

  const jobs = useMemo(() => historyQuery.data ?? [], [historyQuery.data]);
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
          <p className="page-header__eyebrow">Scheduler accounting</p>
          <h1>Job history</h1>
          <p>
            Recent jobs for your account on{" "}
            <strong>{selectedCluster?.name ?? "the selected cluster"}</strong>.
          </p>
        </div>
        {historyQuery.data ? (
          <RefreshButton
            isRefreshing={historyQuery.isFetching}
            onRefresh={() => {
              void historyQuery.refetch();
            }}
          />
        ) : null}
      </header>

      {historyQuery.isLoading ? (
        <LoadingState label="Loading job history…" variant="table" />
      ) : historyQuery.error ? (
        <ErrorState
          error={historyQuery.error}
          onRetry={() => {
            void historyQuery.refetch();
          }}
        />
      ) : jobs.length === 0 ? (
        <EmptyState
          title="No recent jobs"
          description="No scheduler accounting records were found for the configured user."
        />
      ) : (
        <>
          <section className="filters" aria-label="Job history filters">
            <div className="field field--search">
              <label htmlFor="history-search">Search history</label>
              <div className="search-input">
                <span aria-hidden="true">⌕</span>
                <input
                  id="history-search"
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
              <label htmlFor="history-state-filter">State</label>
              <select
                id="history-state-filter"
                value={filters.state}
                onChange={(event) =>
                  setFilters((current) => ({
                    ...current,
                    state: event.target.value as JobStateGroup | "all",
                  }))
                }
              >
                <option value="all">All states</option>
                <option value="completed">Completed</option>
                <option value="failed">Failed or cancelled</option>
                <option value="running">Running</option>
                <option value="pending">Pending</option>
                <option value="other">Other</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="history-partition-filter">Partition</label>
              <select
                id="history-partition-filter"
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
              <strong>{jobs.length}</strong> recent jobs
            </span>
            <span>
              Updates automatically every {refresh.history_seconds}{" "}
              {refresh.history_seconds === 1 ? "second" : "seconds"}
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
                  Reset history filters
                </button>
              }
            />
          ) : (
            <JobsTable
              jobs={visibleJobs}
              sort={sort}
              onSort={setSort}
              variant="history"
            />
          )}
        </>
      )}
    </div>
  );
}
