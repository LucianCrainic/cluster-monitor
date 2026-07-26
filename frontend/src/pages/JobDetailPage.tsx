import { useState } from "react";
import { Link, useParams } from "react-router";

import { useCancelJobMutation, useJobQuery } from "../api/queries";
import { ErrorState, LoadingState } from "../components/PageState";
import { RefreshButton } from "../components/RefreshButton";
import { JobStateBadge } from "../components/StatusBadge";
import { useCluster } from "../context/useCluster";
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

  if (jobQuery.isLoading) {
    return (
      <div className="page">
        <LoadingState label="Loading job details…" variant="detail" />
      </div>
    );
  }

  if (jobQuery.error) {
    return (
      <div className="page">
        <Link className="back-link" to="/jobs">
          ← Back to jobs
        </Link>
        <ErrorState
          error={jobQuery.error}
          onRetry={() => {
            void jobQuery.refetch();
          }}
          title="Job details unavailable"
        />
      </div>
    );
  }

  const job = jobQuery.data;
  if (!job) {
    return null;
  }
  const isActive =
    job.state === "pending" ||
    job.state === "running" ||
    job.state === "suspended";
  const hasUnsupportedScope =
    job.array_job_id != null || job.heterogeneous_job_id != null;
  const hasCancelableId =
    /^[1-9][0-9]*$/.test(job.job_id) && !hasUnsupportedScope;
  const canCancel =
    isActive &&
    hasCancelableId &&
    selectedCluster?.job_actions_enabled === true;

  return (
    <div className="page">
      <Link className="back-link" to="/jobs">
        ← Back to jobs
      </Link>
      <header className="page-header job-detail-header">
        <div>
          <p className="page-header__eyebrow">Job {job.job_id}</p>
          <div className="job-detail-header__title">
            <h1>{job.job_name}</h1>
            <JobStateBadge state={job.state} />
          </div>
          <p>
            Submitted by <strong>{job.user}</strong> to{" "}
            <strong>{job.partition}</strong>.
          </p>
        </div>
        <div className="page-header__actions">
          {canCancel && !cancelMutation.data ? (
            <button
              className="button button--danger"
              type="button"
              disabled={cancelMutation.isPending}
              onClick={() => setConfirmingCancellation(true)}
            >
              Cancel job
            </button>
          ) : isActive && selectedCluster?.job_actions_enabled !== true ? (
            <span className="job-actions-disabled" role="note">
              Job actions are disabled for this cluster.
            </span>
          ) : isActive && !hasCancelableId ? (
            <span className="job-actions-disabled" role="note">
              Array and heterogeneous job cancellation is not supported yet.
            </span>
          ) : null}
          <RefreshButton
            isRefreshing={jobQuery.isFetching}
            onRefresh={() => {
              void jobQuery.refetch();
            }}
          />
        </div>
      </header>

      {cancelMutation.data ? (
        <div
          className="job-action-feedback job-action-feedback--success"
          role="status"
          aria-live="polite"
        >
          <strong>
            Cancellation requested for job {cancelMutation.data.job_id}.
          </strong>
          <p>Refresh the job to confirm its final scheduler state.</p>
        </div>
      ) : null}

      {confirmingCancellation && !cancelMutation.data ? (
        <section
          className="job-cancel-confirmation"
          role="alertdialog"
          aria-labelledby="cancel-job-heading"
          aria-describedby="cancel-job-description"
        >
          <p className="section-eyebrow">Confirmation required</p>
          <h2 id="cancel-job-heading">Cancel job {job.job_id}?</h2>
          <p id="cancel-job-description">
            This asks Slurm to stop job {job.job_id}. Running work may end
            immediately, and this action cannot be undone from Cluster Monitor.
          </p>
          {cancelMutation.error ? (
            <div
              className="job-action-feedback job-action-feedback--error"
              role="alert"
            >
              <strong>Cancellation was not confirmed for job {job.job_id}.</strong>
              <p>{cancelMutation.error.message}</p>
            </div>
          ) : null}
          <div className="job-action-buttons">
            <button
              className="button button--secondary"
              type="button"
              disabled={cancelMutation.isPending}
              onClick={() => {
                cancelMutation.reset();
                setConfirmingCancellation(false);
              }}
            >
              Keep job {job.job_id}
            </button>
            <button
              className="button button--danger"
              type="button"
              disabled={cancelMutation.isPending}
              onClick={() => cancelMutation.mutate()}
            >
              {cancelMutation.isPending
                ? `Cancelling job ${job.job_id}…`
                : `Yes, cancel job ${job.job_id}`}
            </button>
          </div>
        </section>
      ) : null}

      <div className="detail-layout">
        <section className="detail-card" aria-labelledby="job-summary-heading">
          <div className="detail-card__header">
            <p className="section-eyebrow">Scheduler</p>
            <h2 id="job-summary-heading">Job summary</h2>
          </div>
          <dl className="detail-list">
            <Detail label="Job ID" value={job.job_id} mono />
            <Detail label="Raw state" value={job.state_raw} />
            <Detail label="Pending reason" value={job.reason} />
            <Detail label="Nodes" value={job.nodes} />
            <Detail
              label="Node list"
              value={
                job.node_list && job.node_list.length > 0
                  ? job.node_list.join(", ")
                  : null
              }
              mono
            />
            <Detail label="Requested CPUs" value={job.requested_cpus} />
            <Detail label="Requested memory" value={formatMemory(job.requested_memory_mb)} />
            <Detail label="Requested GPUs" value={job.requested_gpus} />
            <Detail label="Elapsed" value={formatDuration(job.elapsed_seconds)} />
            <Detail label="Time limit" value={formatDuration(job.time_limit_seconds)} />
          </dl>
        </section>

        <section className="detail-card" aria-labelledby="job-timeline-heading">
          <div className="detail-card__header">
            <p className="section-eyebrow">Lifecycle</p>
            <h2 id="job-timeline-heading">Timeline</h2>
          </div>
          <dl className="detail-list">
            <Detail label="Submitted" value={formatDateTime(job.submit_time)} />
            <Detail label="Started" value={formatDateTime(job.start_time)} />
            <Detail label="Ended" value={formatDateTime(job.end_time)} />
            <Detail label="Exit code" value={job.exit_code} mono />
          </dl>
        </section>

        <section className="detail-card detail-card--wide" aria-labelledby="job-io-heading">
          <div className="detail-card__header">
            <p className="section-eyebrow">Execution</p>
            <h2 id="job-io-heading">Command and paths</h2>
          </div>
          <dl className="detail-list">
            <Detail label="Working directory" value={job.working_directory} mono />
            <Detail label="Command" value={job.command} mono />
            <Detail label="Standard output" value={job.standard_output_path} mono />
            <Detail label="Standard error" value={job.standard_error_path} mono />
          </dl>
        </section>

        <ObjectDetails
          title="Allocation details"
          eyebrow="Resources"
          details={job.allocation_details}
        />
        <ObjectDetails
          title="Accounting"
          eyebrow="Usage"
          details={job.accounting}
        />
      </div>
    </div>
  );
}

function Detail({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string | number | null | undefined;
  mono?: boolean;
}) {
  return (
    <div>
      <dt>{label}</dt>
      <dd className={mono ? "detail-list__mono" : undefined}>
        {displayValue(value)}
      </dd>
    </div>
  );
}

function ObjectDetails({
  title,
  eyebrow,
  details,
}: {
  title: string;
  eyebrow: string;
  details: Record<string, unknown> | object | null | undefined;
}) {
  const entries = details ? Object.entries(details) : [];
  return (
    <section className="detail-card" aria-labelledby={`${title.replace(/\s/g, "-")}-heading`}>
      <div className="detail-card__header">
        <p className="section-eyebrow">{eyebrow}</p>
        <h2 id={`${title.replace(/\s/g, "-")}-heading`}>{title}</h2>
      </div>
      {entries.length > 0 ? (
        <dl className="detail-list">
          {entries.map(([key, value]) => (
            <Detail
              key={key}
              label={titleCase(key)}
              value={
                typeof value === "object"
                  ? JSON.stringify(value)
                  : String(value)
              }
              mono
            />
          ))}
        </dl>
      ) : (
        <p className="detail-card__empty">No {title.toLowerCase()} reported.</p>
      )}
    </section>
  );
}
