import { useMemo, type CSSProperties } from "react";
import { Link } from "react-router";

import {
  useHistoryQuery,
  useJobsQuery,
  useOverviewQuery,
} from "../api/queries";
import { Icon, type IconName } from "../components/Icon";
import { MetricCard } from "../components/MetricCard";
import { ErrorState, LoadingState } from "../components/PageState";
import { RefreshButton } from "../components/RefreshButton";
import { ConnectionBadge, JobStateBadge } from "../components/StatusBadge";
import { useCluster } from "../context/useCluster";
import type { Job } from "../types/api";
import {
  formatDateTime,
  formatDuration,
  formatMemory,
  formatRelativeTime,
} from "../utils/format";
import { getCapacitySegments } from "../utils/overview";

export function OverviewPage() {
  const { selectedCluster, selectedClusterId } = useCluster();
  const overviewQuery = useOverviewQuery(selectedClusterId);
  const jobsQuery = useJobsQuery(selectedClusterId);
  const historyQuery = useHistoryQuery(selectedClusterId);

  return (
    <div className="page overview-page">
      <header className="page-header">
        <div>
          <p className="page-header__eyebrow">Operations dashboard</p>
          <h1>Overview</h1>
          <p>
            Live capacity, workload, and recent outcomes for{" "}
            <strong>{selectedCluster?.name ?? "the selected cluster"}</strong>.
          </p>
        </div>
        {overviewQuery.data ? (
          <RefreshButton
            isRefreshing={
              overviewQuery.isFetching || jobsQuery.isFetching || historyQuery.isFetching
            }
            onRefresh={() => {
              void Promise.all([
                overviewQuery.refetch(),
                jobsQuery.refetch(),
                historyQuery.refetch(),
              ]);
            }}
          />
        ) : null}
      </header>

      {overviewQuery.isLoading ? (
        <LoadingState label="Loading cluster overview…" />
      ) : overviewQuery.error ? (
        <ErrorState
          error={overviewQuery.error}
          onRetry={() => void overviewQuery.refetch()}
        />
      ) : overviewQuery.data ? (
        <OverviewContent
          overview={overviewQuery.data}
          jobs={jobsQuery.data ?? []}
          history={historyQuery.data ?? []}
          actionsEnabled={selectedCluster?.job_actions_enabled === true}
          filesEnabled={selectedCluster?.file_browser_enabled === true}
        />
      ) : null}
    </div>
  );
}

function OverviewContent({
  overview,
  jobs,
  history,
  actionsEnabled,
  filesEnabled,
}: {
  overview: NonNullable<ReturnType<typeof useOverviewQuery>["data"]>;
  jobs: Job[];
  history: Job[];
  actionsEnabled: boolean;
  filesEnabled: boolean;
}) {
  const capacity = getCapacitySegments(overview);
  const activeJobs = useMemo(
    () => jobs.filter((job) => ["running", "pending", "suspended"].includes(job.state)),
    [jobs],
  );
  const workload = useMemo(() => summarizeWorkload(activeJobs), [activeJobs]);
  const recent = useMemo(() => summarizeHistory(history), [history]);
  const utilization = overview.total_nodes
    ? Math.round((overview.allocated_nodes / overview.total_nodes) * 100)
    : 0;

  return (
    <>
      <section className="connection-card" aria-labelledby="connection-heading">
        <div className="connection-card__status">
          <p className="section-eyebrow">Connection</p>
          <div className="connection-card__title-row">
            <h2 id="connection-heading">
              {overview.connection_status === "connected"
                ? "Cluster is reachable"
                : "Cluster needs attention"}
            </h2>
            <ConnectionBadge status={overview.connection_status} />
          </div>
          {overview.last_error ? (
            <p className="connection-card__error">{overview.last_error}</p>
          ) : (
            <p>Scheduler commands are responding normally through the secured local service.</p>
          )}
          <div className="capability-row" aria-label="Enabled capabilities">
            <span className={actionsEnabled ? "is-enabled" : ""}>
              {actionsEnabled ? "Job control enabled" : "Monitoring only"}
            </span>
            <span className={filesEnabled ? "is-enabled" : ""}>
              {filesEnabled ? "File access enabled" : "Files disabled"}
            </span>
          </div>
        </div>
        <dl className="connection-card__meta">
          <div><dt>Slurm version</dt><dd>{overview.slurm_version ?? "Not reported"}</dd></div>
          <div>
            <dt>Last refreshed</dt>
            <dd title={formatDateTime(overview.last_refresh)}>
              {formatRelativeTime(overview.last_refresh)}
            </dd>
          </div>
          <div><dt>Node utilization</dt><dd>{utilization}% allocated</dd></div>
          <div><dt>Queue depth</dt><dd>{overview.pending_jobs.toLocaleString()} waiting</dd></div>
        </dl>
      </section>

      <section className="overview-workload" aria-labelledby="workload-heading">
        <div className="section-heading">
          <div><p className="section-eyebrow">Your workload</p><h2 id="workload-heading">Active allocation</h2></div>
          <Link to="/jobs">Open job queue →</Link>
        </div>
        <div className="workload-strip">
          <WorkloadMetric icon="jobs" label="Active jobs" value={activeJobs.length.toLocaleString()} detail={`${overview.running_jobs} running · ${overview.pending_jobs} pending`} />
          <WorkloadMetric icon="cpu" label="Requested CPUs" value={workload.cpus.toLocaleString()} detail="Across active jobs" />
          <WorkloadMetric icon="memory" label="Requested memory" value={formatMemory(workload.memoryMb)} detail="Across reported requests" />
          <WorkloadMetric icon="gpu" label="Requested GPUs" value={workload.gpus.toLocaleString()} detail="Across active jobs" />
        </div>
      </section>

      <section aria-labelledby="nodes-heading">
        <div className="section-heading">
          <div><p className="section-eyebrow">Infrastructure</p><h2 id="nodes-heading">Node capacity</h2></div>
          <Link to="/topology">Explore topology →</Link>
        </div>
        <div className="metric-grid metric-grid--nodes">
          <MetricCard label="Total nodes" value={overview.total_nodes} detail="Configured resources" />
          <MetricCard label="Idle" value={overview.idle_nodes} tone="positive" detail="Ready for work" />
          <MetricCard label="Allocated" value={overview.allocated_nodes} tone="info" detail="Currently in use" />
          <MetricCard label="Unavailable" value={overview.unavailable_nodes} tone={overview.unavailable_nodes > 0 ? "danger" : "default"} detail="Drained, down, or unknown" />
        </div>
        <div className="capacity-bar-card">
          <div
            className="capacity-bar"
            role="img"
            aria-label={capacity.map((segment) => `${segment.label}: ${segment.value}`).join(", ")}
          >
            {capacity.map((segment) => (
              <span key={segment.key} className={`capacity-bar__segment capacity-bar__segment--${segment.key}`} style={{ width: `${segment.percentage}%` }} />
            ))}
          </div>
          <ul className="capacity-legend" aria-hidden="true">
            {capacity.map((segment) => (
              <li key={segment.key}>
                <span className={`capacity-legend__dot capacity-legend__dot--${segment.key}`} />
                {segment.label}<strong>{segment.value}</strong>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="overview-history" aria-labelledby="history-summary-heading">
        <div className="section-heading">
          <div><p className="section-eyebrow">Last seven days</p><h2 id="history-summary-heading">Recent outcomes</h2></div>
          <Link to="/history">View full history →</Link>
        </div>
        <div className="overview-history__layout">
          <div className="history-stats">
            <div className="success-ring" style={{ "--progress": `${recent.successRate}%` } as CSSProperties}>
              <div><strong>{recent.successRate}%</strong><span>success</span></div>
            </div>
            <dl>
              <div><dt>Completed</dt><dd>{recent.completed}</dd></div>
              <div><dt>Failed / stopped</dt><dd>{recent.failed}</dd></div>
              <div><dt>CPU time</dt><dd>{recent.cpuHours.toLocaleString(undefined, { maximumFractionDigits: 1 })} h</dd></div>
              <div><dt>Avg. runtime</dt><dd>{formatDuration(recent.averageRuntime)}</dd></div>
            </dl>
          </div>
          <div className="recent-jobs">
            {history.slice(0, 5).map((job) => (
              <Link key={job.job_id} to={`/jobs/${encodeURIComponent(job.job_id)}`}>
                <span className="recent-jobs__identity"><strong>{job.job_name}</strong><small>#{job.job_id} · {job.partition}</small></span>
                <span className="recent-jobs__duration">{formatDuration(job.elapsed_seconds)}</span>
                <JobStateBadge state={job.state} />
              </Link>
            ))}
            {history.length === 0 ? <p>No recent accounting records are available yet.</p> : null}
          </div>
        </div>
      </section>
    </>
  );
}

function WorkloadMetric({ icon, label, value, detail }: { icon: IconName; label: string; value: string; detail: string }) {
  return (
    <article className="workload-metric">
      <span className="workload-metric__icon"><Icon name={icon} /></span>
      <span><small>{label}</small><strong>{value}</strong><em>{detail}</em></span>
    </article>
  );
}

function summarizeWorkload(jobs: Job[]) {
  return jobs.reduce(
    (total, job) => ({
      cpus: total.cpus + job.requested_cpus,
      memoryMb: total.memoryMb + (job.requested_memory_mb ?? 0),
      gpus: total.gpus + (job.requested_gpus ?? 0),
    }),
    { cpus: 0, memoryMb: 0, gpus: 0 },
  );
}

function summarizeHistory(jobs: Job[]) {
  const finished = jobs.filter((job) => ["completed", "failed", "cancelled", "timeout", "out_of_memory"].includes(job.state));
  const completed = finished.filter((job) => job.state === "completed").length;
  const failed = finished.length - completed;
  const runtime = finished.reduce((total, job) => total + job.elapsed_seconds, 0);
  const cpuSeconds = finished.reduce((total, job) => total + job.elapsed_seconds * job.requested_cpus, 0);
  return {
    completed,
    failed,
    successRate: finished.length ? Math.round((completed / finished.length) * 100) : 0,
    averageRuntime: finished.length ? Math.round(runtime / finished.length) : 0,
    cpuHours: cpuSeconds / 3_600,
  };
}
