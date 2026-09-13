import { useState, type ReactNode } from "react";
import { Link, useParams } from "react-router";

import { useCancelJobMutation, useJobQuery } from "../api/queries";
import { Icon, type IconName } from "../components/Icon";
import { JobLogViewer } from "../components/JobLogViewer";
import { ErrorState, LoadingState } from "../components/PageState";
import { RefreshButton } from "../components/RefreshButton";
import { JobStateBadge } from "../components/StatusBadge";
import { useCluster } from "../context/useCluster";
import type { JobDetails } from "../types/api";
import {
  displayValue,
  formatDateTime,
  formatDuration,
  formatMemory,
  titleCase,
} from "../utils/format";

export function JobDetailPage() {
  const { jobId = null } = useParams();
  const { selectedCluster, selectedClusterId } = useCluster();
  const jobQuery = useJobQuery(selectedClusterId, jobId);
  const cancelMutation = useCancelJobMutation(selectedClusterId, jobId);
  const [confirmingCancellation, setConfirmingCancellation] = useState(false);
  const [activeTab, setActiveTab] = useState<"overview" | "logs">("overview");

  if (jobQuery.isLoading) {
    return <div className="page"><LoadingState label="Loading job details…" variant="detail" /></div>;
  }
  if (jobQuery.error) {
    return (
      <div className="page">
        <Link className="back-link" to="/jobs">← Back to jobs</Link>
        <ErrorState error={jobQuery.error} onRetry={() => void jobQuery.refetch()} title="Job details unavailable" />
      </div>
    );
  }

  const job = jobQuery.data;
  if (!job || !selectedClusterId) return null;

  const isActive = ["pending", "running", "suspended"].includes(job.state);
  const hasUnsupportedScope = job.array_job_id != null || job.heterogeneous_job_id != null;
  const hasCancelableId = /^[1-9][0-9]*$/.test(job.job_id) && !hasUnsupportedScope;
  const canCancel = isActive && hasCancelableId && selectedCluster?.job_actions_enabled === true;

  return (
    <div className="page job-detail-page">
      <Link className="back-link" to="/jobs">← Back to jobs</Link>
      <header className="page-header job-detail-header">
        <div>
          <p className="page-header__eyebrow">Job #{job.job_id}</p>
          <div className="job-detail-header__title">
            <h1>{job.job_name}</h1>
            <JobStateBadge state={job.state} />
          </div>
          <p>
            <strong>{job.partition}</strong> · submitted by <strong>{job.user}</strong>
            {job.node_list?.length ? ` · allocated on ${job.node_list.length} node${job.node_list.length === 1 ? "" : "s"}` : ""}
          </p>
        </div>
        <div className="page-header__actions">
          <Link className="button button--secondary" to={`/topology?job=${encodeURIComponent(job.job_id)}`}>View allocation</Link>
          {canCancel && !cancelMutation.data ? (
            <button className="button button--danger" type="button" disabled={cancelMutation.isPending} onClick={() => setConfirmingCancellation(true)}>Cancel job</button>
          ) : isActive && selectedCluster?.job_actions_enabled !== true ? (
            <span className="job-actions-disabled" role="note">Job actions are disabled for this cluster.</span>
          ) : isActive && !hasCancelableId ? (
            <span className="job-actions-disabled" role="note">Array and heterogeneous job cancellation is not supported yet.</span>
          ) : null}
          <RefreshButton isRefreshing={jobQuery.isFetching} onRefresh={() => void jobQuery.refetch()} />
        </div>
      </header>

      <JobAtAGlance job={job} />

      {cancelMutation.data ? (
        <div className="job-action-feedback job-action-feedback--success" role="status" aria-live="polite">
          <strong>Cancellation requested for job {cancelMutation.data.job_id}.</strong>
          <p>Refresh the job to confirm its final scheduler state.</p>
        </div>
      ) : null}

      {confirmingCancellation && !cancelMutation.data ? (
        <section className="job-cancel-confirmation" role="alertdialog" aria-labelledby="cancel-job-heading" aria-describedby="cancel-job-description">
          <p className="section-eyebrow">Confirmation required</p>
          <h2 id="cancel-job-heading">Cancel job {job.job_id}?</h2>
          <p id="cancel-job-description">This asks Slurm to stop job {job.job_id}. Running work may end immediately, and this action cannot be undone from Cluster Monitor.</p>
          {cancelMutation.error ? (
            <div className="job-action-feedback job-action-feedback--error" role="alert">
              <strong>Cancellation was not confirmed for job {job.job_id}.</strong>
              <p>{cancelMutation.error.message}</p>
            </div>
          ) : null}
          <div className="job-action-buttons">
            <button className="button button--secondary" type="button" disabled={cancelMutation.isPending} onClick={() => { cancelMutation.reset(); setConfirmingCancellation(false); }}>Keep job {job.job_id}</button>
            <button className="button button--danger" type="button" disabled={cancelMutation.isPending} onClick={() => cancelMutation.mutate()}>
              {cancelMutation.isPending ? `Cancelling job ${job.job_id}…` : `Yes, cancel job ${job.job_id}`}
            </button>
          </div>
        </section>
      ) : null}

      <div
        className="job-detail-tabs"
        role="tablist"
        aria-label="Job details"
        onKeyDown={(event) => {
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
          event.preventDefault();
          const nextTab = event.key === "ArrowRight" || event.key === "End" ? "logs" : "overview";
          setActiveTab(nextTab);
          requestAnimationFrame(() => document.getElementById(`job-${nextTab}-tab`)?.focus());
        }}
      >
        <button id="job-overview-tab" type="button" role="tab" aria-selected={activeTab === "overview"} aria-controls="job-overview-panel" tabIndex={activeTab === "overview" ? 0 : -1} onClick={() => setActiveTab("overview")}>Overview</button>
        <button id="job-logs-tab" type="button" role="tab" aria-selected={activeTab === "logs"} aria-controls="job-logs-panel" tabIndex={activeTab === "logs" ? 0 : -1} onClick={() => setActiveTab("logs")}>Logs</button>
      </div>

      {activeTab === "overview" ? (
        <JobOverview job={job} />
      ) : (
        <div id="job-logs-panel" role="tabpanel" aria-labelledby="job-logs-tab">
          <JobLogViewer clusterId={selectedClusterId} jobId={job.job_id} />
        </div>
      )}
    </div>
  );
}

function JobAtAGlance({ job }: { job: JobDetails }) {
  const progress = job.time_limit_seconds
    ? Math.min(100, Math.round((job.elapsed_seconds / job.time_limit_seconds) * 100))
    : null;
  return (
    <section className="job-glance" aria-label="Job at a glance">
      <GlanceMetric icon="clock" label="Elapsed" value={formatDuration(job.elapsed_seconds)} detail={job.time_limit_seconds ? `${progress}% of ${formatDuration(job.time_limit_seconds)} limit` : "No limit reported"} />
      <GlanceMetric icon="nodes" label="Nodes" value={job.nodes.toLocaleString()} detail={job.node_list?.length ? job.node_list.join(", ") : "Awaiting allocation"} mono />
      <GlanceMetric icon="cpu" label="CPUs" value={job.requested_cpus.toLocaleString()} detail={`${Math.round(job.requested_cpus / Math.max(job.nodes, 1))} per node`} />
      <GlanceMetric icon="memory" label="Memory" value={formatMemory(job.requested_memory_mb)} detail={job.requested_gpus ? `${job.requested_gpus} GPUs requested` : "No GPUs requested"} />
      {progress != null ? <span className="job-glance__progress" style={{ width: `${progress}%` }} /> : null}
    </section>
  );
}

function GlanceMetric({ icon, label, value, detail, mono = false }: { icon: IconName; label: string; value: string; detail: string; mono?: boolean }) {
  return (
    <article><span className="job-glance__icon"><Icon name={icon} /></span><div><small>{label}</small><strong>{value}</strong><em className={mono ? "is-mono" : undefined} title={detail}>{detail}</em></div></article>
  );
}

function JobOverview({ job }: { job: JobDetails }) {
  const queuedSeconds = secondsBetween(job.submit_time, job.start_time);
  const lifecycle = [
    { label: "Submitted", value: formatDateTime(job.submit_time), complete: Boolean(job.submit_time), detail: queuedSeconds == null ? null : `Queued for ${formatDuration(queuedSeconds)}` },
    { label: "Started", value: formatDateTime(job.start_time), complete: Boolean(job.start_time), detail: job.start_time ? `Ran for ${formatDuration(job.elapsed_seconds)}` : job.reason ?? "Waiting for scheduler" },
    { label: job.end_time ? "Finished" : "Finish", value: formatDateTime(job.end_time), complete: Boolean(job.end_time), detail: job.exit_code ? `Exit code ${job.exit_code}` : null },
  ];
  return (
    <div id="job-overview-panel" role="tabpanel" aria-labelledby="job-overview-tab">
      {job.reason && job.state === "pending" ? (
        <div className="pending-callout"><strong>Why this job is waiting</strong><span>{job.reason}</span></div>
      ) : null}

      <section className="job-lifecycle" aria-labelledby="job-timeline-heading">
        <div className="detail-card__header"><p className="section-eyebrow">Lifecycle</p><h2 id="job-timeline-heading">Timeline</h2></div>
        <ol>
          {lifecycle.map((event) => (
            <li key={event.label} className={event.complete ? "is-complete" : ""}>
              <span className="job-lifecycle__marker" />
              <div><small>{event.label}</small><strong>{event.value}</strong>{event.detail ? <em>{event.detail}</em> : null}</div>
            </li>
          ))}
        </ol>
      </section>

      <div className="job-overview-grid">
        <section className="detail-card job-summary-card" aria-labelledby="job-summary-heading">
          <div className="detail-card__header"><p className="section-eyebrow">Scheduler</p><h2 id="job-summary-heading">Job summary</h2></div>
          <dl className="detail-list">
            <Detail label="Job ID" value={job.job_id} mono />
            <Detail label="State from Slurm" value={job.state_raw} />
            <Detail label="User" value={job.user} />
            <Detail label="Partition" value={job.partition} />
            <Detail label="Pending reason" value={job.reason} />
            <Detail label="Exit code" value={job.exit_code} mono />
          </dl>
        </section>

        <section className="detail-card resource-card" aria-labelledby="job-resource-heading">
          <div className="detail-card__header"><p className="section-eyebrow">Allocation</p><h2 id="job-resource-heading">Requested resources</h2></div>
          <div className="resource-card__grid">
            <ResourceValue icon="nodes" label="Nodes" value={job.nodes} />
            <ResourceValue icon="cpu" label="CPUs" value={job.requested_cpus} />
            <ResourceValue icon="memory" label="Memory" value={formatMemory(job.requested_memory_mb)} />
            <ResourceValue icon="gpu" label="GPUs" value={job.requested_gpus ?? 0} />
          </div>
          <div className="resource-card__nodes">
            <span>Allocated nodes</span>
            <code>{job.node_list?.length ? job.node_list.join(", ") : "Not assigned yet"}</code>
          </div>
        </section>

        <section className="detail-card detail-card--wide execution-card" aria-labelledby="job-io-heading">
          <div className="detail-card__header"><p className="section-eyebrow">Execution</p><h2 id="job-io-heading">Command and output</h2></div>
          <div className="execution-paths">
            <CodeValue label="Working directory" value={job.working_directory} />
            <CodeValue label="Command" value={job.command} />
            <CodeValue label="Standard output" value={job.standard_output_path} />
            <CodeValue label="Standard error" value={job.standard_error_path} />
          </div>
        </section>

        <ObjectDetails title="Allocation details" eyebrow="Scheduler metadata" details={job.allocation_details} />
        <AccountingDetails accounting={job.accounting} />
      </div>
    </div>
  );
}

function ResourceValue({ icon, label, value }: { icon: "nodes" | "cpu" | "memory" | "gpu"; label: string; value: string | number }) {
  return <div><span><Icon name={icon} /></span><small>{label}</small><strong>{value}</strong></div>;
}

function CodeValue({ label, value }: { label: string; value: string | null | undefined }) {
  return <div><span>{label}</span><code>{displayValue(value, "Not reported by Slurm")}</code></div>;
}

function Detail({ label, value, mono = false }: { label: string; value: string | number | null | undefined; mono?: boolean }) {
  return <div><dt>{label}</dt><dd className={mono ? "detail-list__mono" : undefined}>{displayValue(value)}</dd></div>;
}

function ObjectDetails({ title, eyebrow, details }: { title: string; eyebrow: string; details: Record<string, unknown> | object | null | undefined }) {
  const entries = details ? Object.entries(details) : [];
  return (
    <section className="detail-card" aria-labelledby={`${title.replace(/\s/g, "-")}-heading`}>
      <div className="detail-card__header"><p className="section-eyebrow">{eyebrow}</p><h2 id={`${title.replace(/\s/g, "-")}-heading`}>{title}</h2></div>
      {entries.length > 0 ? (
        <dl className="detail-list">{entries.map(([key, value]) => <Detail key={key} label={titleCase(key)} value={typeof value === "object" ? JSON.stringify(value) : String(value)} mono />)}</dl>
      ) : <p className="detail-card__empty">No {title.toLowerCase()} reported.</p>}
    </section>
  );
}

function AccountingDetails({ accounting }: { accounting: JobDetails["accounting"] }) {
  const values: Array<{ label: string; value: ReactNode }> = [
    { label: "CPU time", value: formatDuration(accounting?.elapsed_cpu_seconds) },
    { label: "Peak memory", value: formatMemory(accounting?.max_rss_mb) },
    { label: "Energy", value: accounting?.consumed_energy_joules == null ? "—" : `${accounting.consumed_energy_joules.toLocaleString()} J` },
  ];
  return (
    <section className="detail-card" aria-labelledby="accounting-heading">
      <div className="detail-card__header"><p className="section-eyebrow">Usage</p><h2 id="accounting-heading">Accounting</h2></div>
      <div className="accounting-grid">{values.map((item) => <div key={item.label}><small>{item.label}</small><strong>{item.value}</strong></div>)}</div>
      {!accounting ? <p className="detail-card__empty">Accounting data appears after Slurm records job usage.</p> : null}
    </section>
  );
}

function secondsBetween(start: string | null | undefined, end: string | null | undefined) {
  if (!start || !end) return null;
  const seconds = Math.round((new Date(end).getTime() - new Date(start).getTime()) / 1000);
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
}
