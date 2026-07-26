import { useOverviewQuery } from "../api/queries";
import { MetricCard } from "../components/MetricCard";
import { ErrorState, LoadingState } from "../components/PageState";
import { RefreshButton } from "../components/RefreshButton";
import { ConnectionBadge } from "../components/StatusBadge";
import { useCluster } from "../context/useCluster";
import { formatDateTime, formatRelativeTime } from "../utils/format";
import { getCapacitySegments } from "../utils/overview";

export function OverviewPage() {
  const { selectedCluster, selectedClusterId } = useCluster();
  const overviewQuery = useOverviewQuery(selectedClusterId);

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <p className="page-header__eyebrow">Cluster health</p>
          <h1>Overview</h1>
          <p>
            A live snapshot of{" "}
            <strong>{selectedCluster?.name ?? "the selected cluster"}</strong>.
          </p>
        </div>
        {overviewQuery.data ? (
          <RefreshButton
            isRefreshing={overviewQuery.isFetching}
            onRefresh={() => {
              void overviewQuery.refetch();
            }}
          />
        ) : null}
      </header>

      {overviewQuery.isLoading ? (
        <LoadingState label="Loading cluster overview…" />
      ) : overviewQuery.error ? (
        <ErrorState
          error={overviewQuery.error}
          onRetry={() => {
            void overviewQuery.refetch();
          }}
        />
      ) : overviewQuery.data ? (
        <OverviewContent overview={overviewQuery.data} />
      ) : null}
    </div>
  );
}

function OverviewContent({
  overview,
}: {
  overview: NonNullable<ReturnType<typeof useOverviewQuery>["data"]>;
}) {
  const capacity = getCapacitySegments(overview);

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
            <p>Commands are responding normally through the local service.</p>
          )}
        </div>
        <dl className="connection-card__meta">
          <div>
            <dt>Slurm version</dt>
            <dd>{overview.slurm_version ?? "Not reported"}</dd>
          </div>
          <div>
            <dt>Last refreshed</dt>
            <dd title={formatDateTime(overview.last_refresh)}>
              {formatRelativeTime(overview.last_refresh)}
            </dd>
          </div>
        </dl>
      </section>

      <section aria-labelledby="nodes-heading">
        <div className="section-heading">
          <div>
            <p className="section-eyebrow">Infrastructure</p>
            <h2 id="nodes-heading">Node capacity</h2>
          </div>
          <span>{overview.total_nodes.toLocaleString()} total nodes</span>
        </div>
        <div className="metric-grid metric-grid--nodes">
          <MetricCard
            label="Total nodes"
            value={overview.total_nodes}
            detail="Configured resources"
          />
          <MetricCard
            label="Idle"
            value={overview.idle_nodes}
            tone="positive"
            detail="Ready for work"
          />
          <MetricCard
            label="Allocated"
            value={overview.allocated_nodes}
            tone="info"
            detail="Currently in use"
          />
          <MetricCard
            label="Unavailable"
            value={overview.unavailable_nodes}
            tone={overview.unavailable_nodes > 0 ? "danger" : "default"}
            detail="Drained or down"
          />
        </div>

        <div className="capacity-bar-card">
          <div
            className="capacity-bar"
            role="img"
            aria-label={capacity
              .map((segment) => `${segment.label}: ${segment.value}`)
              .join(", ")}
          >
            {capacity.map((segment) => (
              <span
                key={segment.key}
                className={`capacity-bar__segment capacity-bar__segment--${segment.key}`}
                style={{ width: `${segment.percentage}%` }}
              />
            ))}
          </div>
          <ul className="capacity-legend" aria-hidden="true">
            {capacity.map((segment) => (
              <li key={segment.key}>
                <span
                  className={`capacity-legend__dot capacity-legend__dot--${segment.key}`}
                />
                {segment.label}
                <strong>{segment.value}</strong>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section aria-labelledby="workload-heading">
        <div className="section-heading">
          <div>
            <p className="section-eyebrow">Scheduler</p>
            <h2 id="workload-heading">Your workload</h2>
          </div>
          <span>Current queue</span>
        </div>
        <div className="metric-grid metric-grid--jobs">
          <MetricCard
            label="Running jobs"
            value={overview.running_jobs}
            tone="info"
            detail="Actively consuming resources"
          />
          <MetricCard
            label="Pending jobs"
            value={overview.pending_jobs}
            tone={overview.pending_jobs > 0 ? "warning" : "default"}
            detail="Waiting in the scheduler"
          />
        </div>
      </section>
    </>
  );
}
