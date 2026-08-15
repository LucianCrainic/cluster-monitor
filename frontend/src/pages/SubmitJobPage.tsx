import { useRef, useState, type FormEvent } from "react";
import { Link } from "react-router";

import { useSubmitJobMutation, useTopologyQuery } from "../api/queries";
import { PartitionCards } from "../components/PartitionCards";
import { RemoteFileBrowser } from "../components/RemoteFileBrowser";
import { useCluster } from "../context/useCluster";
import type { SubmitJobRequest } from "../types/api";
import { formatDateTime } from "../utils/format";
import "./jobActions.css";

const STARTER_SCRIPT = `#!/bin/bash
set -euo pipefail

echo "Starting Slurm job"
srun hostname
`;

interface SubmissionDraft {
  jobName: string;
  script: string;
  partition: string;
  nodes: string;
  cpusPerTask: string;
  memoryMb: string;
  timeLimitMinutes: string;
  gpusPerNode: string;
}

interface ReviewedSubmission {
  clusterId: string;
  clusterName: string;
  submission: SubmitJobRequest;
}

const INITIAL_DRAFT: SubmissionDraft = {
  jobName: "cluster-monitor-job",
  script: STARTER_SCRIPT,
  partition: "",
  nodes: "1",
  cpusPerTask: "1",
  memoryMb: "1024",
  timeLimitMinutes: "10",
  gpusPerNode: "0",
};

export function SubmitJobPage() {
  const { selectedCluster, selectedClusterId } = useCluster();
  const [draft, setDraft] = useState<SubmissionDraft>(INITIAL_DRAFT);
  const [review, setReview] = useState<ReviewedSubmission | null>(null);
  const [workspaceOpen, setWorkspaceOpen] = useState(true);
  const [workspaceTab, setWorkspaceTab] = useState<"resources" | "files">("resources");
  const [pendingRemoteScript, setPendingRemoteScript] = useState<{ content: string; path: string } | null>(null);
  const scriptRef = useRef<HTMLTextAreaElement>(null);
  const submitMutation = useSubmitJobMutation(selectedClusterId);
  const topologyQuery = useTopologyQuery(selectedClusterId);
  const resetMutation = submitMutation.reset;
  const activeReview =
    review?.clusterId === selectedClusterId ? review : null;
  const actionsEnabled = selectedCluster?.job_actions_enabled === true;

  function updateDraft<Key extends keyof SubmissionDraft>(
    key: Key,
    value: SubmissionDraft[Key],
  ) {
    setDraft((current) => ({ ...current, [key]: value }));
  }

  function prepareReview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedClusterId) {
      return;
    }
    resetMutation();
    setReview({
      clusterId: selectedClusterId,
      clusterName: selectedCluster?.name ?? selectedClusterId,
      submission: {
        job_name: draft.jobName.trim(),
        script: draft.script.trimEnd(),
        partition: draft.partition.trim() || null,
        nodes: Number(draft.nodes),
        cpus_per_task: Number(draft.cpusPerTask),
        memory_mb: draft.memoryMb.trim() ? Number(draft.memoryMb) : null,
        time_limit_minutes: Number(draft.timeLimitMinutes),
        gpus_per_node: Number(draft.gpusPerNode),
      },
    });
  }

  function startAnotherSubmission() {
    setReview(null);
    resetMutation();
  }

  function insertRemotePath(quotedPath: string) {
    const editor = scriptRef.current;
    const start = editor?.selectionStart ?? draft.script.length;
    const end = editor?.selectionEnd ?? start;
    const separator = start > 0 && !/\s/.test(draft.script[start - 1] ?? "") ? " " : "";
    const insertion = `${separator}${quotedPath}`;
    updateDraft(
      "script",
      `${draft.script.slice(0, start)}${insertion}${draft.script.slice(end)}`,
    );
    requestAnimationFrame(() => {
      const cursor = start + insertion.length;
      scriptRef.current?.focus();
      scriptRef.current?.setSelectionRange(cursor, cursor);
    });
  }

  function requestRemoteScript(content: string, path: string) {
    if (draft.script !== STARTER_SCRIPT) {
      setPendingRemoteScript({ content, path });
      return;
    }
    updateDraft("script", content);
  }

  const resourceRequest = {
    nodes: safeNumber(draft.nodes),
    cpusPerNode: safeNumber(draft.cpusPerTask),
    memoryMb: draft.memoryMb.trim() ? safeNumber(draft.memoryMb) : null,
    gpusPerNode: safeNumber(draft.gpusPerNode),
    timeMinutes: safeNumber(draft.timeLimitMinutes),
  };

  if (!actionsEnabled) {
    return (
      <div className="page">
        <Link className="back-link" to="/jobs">
          ← Back to jobs
        </Link>
        <section
          className="job-action-feedback"
          aria-labelledby="job-actions-disabled-heading"
        >
          <p className="section-eyebrow">Scheduler actions</p>
          <h1 id="job-actions-disabled-heading">Job actions are disabled</h1>
          <p>
            Submission and cancellation are not enabled for{" "}
            <strong>{selectedCluster?.name ?? "this cluster"}</strong>.
          </p>
        </section>
      </div>
    );
  }

  if (submitMutation.data) {
    return (
      <div className="page">
        <Link className="back-link" to="/jobs">
          ← Back to jobs
        </Link>
        <section
          className="job-action-feedback job-action-feedback--success"
          role="status"
          aria-live="polite"
        >
          <p className="section-eyebrow">Submitted</p>
          <h1>Job {submitMutation.data.job_id} is in Slurm</h1>
          <p>
            The request was accepted by{" "}
            <strong>
              {review?.clusterId === submitMutation.data.cluster_id
                ? review.clusterName
                : submitMutation.data.cluster_id}
            </strong>{" "}
            at {formatDateTime(submitMutation.data.submitted_at)}.
          </p>
          <div className="job-action-buttons">
            <Link
              className="button button--primary"
              to={`/jobs/${encodeURIComponent(submitMutation.data.job_id)}`}
            >
              View job {submitMutation.data.job_id}
            </Link>
            <button
              className="button button--secondary"
              type="button"
              onClick={startAnotherSubmission}
            >
              Submit another job
            </button>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="page">
      <Link className="back-link" to="/jobs">
        ← Back to jobs
      </Link>
      <header className="page-header">
        <div>
          <p className="page-header__eyebrow">Scheduler action</p>
          <h1>Submit a job</h1>
          <p>
            Prepare a batch script and resource request for{" "}
            <strong>{selectedCluster?.name ?? "the selected cluster"}</strong>.
            Nothing is submitted until you review and confirm it.
          </p>
        </div>
      </header>

      {activeReview ? (
        <JobSubmissionReview
          submission={activeReview.submission}
          clusterName={activeReview.clusterName}
          error={submitMutation.error}
          isPending={submitMutation.isPending}
          onEdit={() => {
            resetMutation();
            setReview(null);
          }}
          onConfirm={() => submitMutation.mutate(activeReview.submission)}
        />
      ) : (
        <form className="job-action-form" onSubmit={prepareReview}>
          <section
            className="job-action-card"
            aria-labelledby="job-identity-heading"
          >
            <div className="job-action-card__header">
              <p className="section-eyebrow">Identity</p>
              <h2 id="job-identity-heading">Job and script</h2>
            </div>

            <div className="job-form-field">
              <label htmlFor="submit-job-name">Job name</label>
              <input
                id="submit-job-name"
                name="job_name"
                value={draft.jobName}
                required
                maxLength={128}
                autoComplete="off"
                onChange={(event) => updateDraft("jobName", event.target.value)}
              />
            </div>

            <div className="job-form-field">
              <label htmlFor="submit-job-script">Batch script</label>
              <p className="job-form-field__hint" id="submit-job-script-hint">
                This safe starter prints the allocated host. Replace it with your
                workload and review every command before submitting. Put scheduler
                options in the resource fields, not in #SBATCH directives.
              </p>
              <textarea
                ref={scriptRef}
                id="submit-job-script"
                name="script"
                value={draft.script}
                required
                rows={12}
                spellCheck={false}
                aria-describedby="submit-job-script-hint"
                onChange={(event) => updateDraft("script", event.target.value)}
              />
            </div>
          </section>

          <section className="preparation-workspace" aria-labelledby="preparation-workspace-heading">
            <button
              className="preparation-workspace__toggle"
              type="button"
              aria-expanded={workspaceOpen}
              aria-controls="preparation-workspace-content"
              onClick={() => setWorkspaceOpen((open) => !open)}
            >
              <span><span className="section-eyebrow">Preparation workspace</span><strong id="preparation-workspace-heading">Inspect before you submit</strong></span>
              <span aria-hidden="true">{workspaceOpen ? "−" : "+"}</span>
            </button>
            {workspaceOpen ? (
              <div id="preparation-workspace-content">
                <div className="preparation-workspace__tabs" role="tablist" aria-label="Preparation workspace">
                  <button type="button" role="tab" aria-selected={workspaceTab === "resources"} onClick={() => setWorkspaceTab("resources")}>Resources</button>
                  <button type="button" role="tab" aria-selected={workspaceTab === "files"} disabled={!selectedCluster?.file_browser_enabled} onClick={() => setWorkspaceTab("files")}>Files</button>
                </div>
                {workspaceTab === "resources" ? (
                  <div className="preparation-workspace__panel" role="tabpanel">
                    <div className="preparation-workspace__intro"><strong>Partition compatibility</strong><p>These checks are advisory and use current Slurm capacity. Slurm still chooses the allocated nodes.</p></div>
                    {topologyQuery.data ? (
                      <PartitionCards
                        topology={topologyQuery.data}
                        selectedPartition={draft.partition || topologyQuery.data.partitions.find((partition) => partition.is_default)?.name}
                        request={resourceRequest}
                        compact
                        onSelect={(partition) => updateDraft("partition", partition.name)}
                      />
                    ) : topologyQuery.error ? (
                      <div className="inline-state"><strong>Partition metadata is unavailable.</strong><span>You can still enter a partition name above and submit normally.</span></div>
                    ) : <p>Loading partition capacity…</p>}
                  </div>
                ) : selectedClusterId && selectedCluster?.file_browser_enabled ? (
                  <div className="preparation-workspace__panel" role="tabpanel">
                    <div className="preparation-workspace__intro"><strong>Read-only remote files</strong><p>Insert a safely quoted path at the script cursor, or copy a remote shell script into this local draft. No remote file is modified.</p></div>
                    <RemoteFileBrowser clusterId={selectedClusterId} compact onInsertPath={insertRemotePath} onUseAsScript={requestRemoteScript} />
                  </div>
                ) : null}
              </div>
            ) : null}
          </section>

          {pendingRemoteScript ? (
            <section className="remote-script-confirmation" role="alertdialog" aria-labelledby="replace-script-heading">
              <p className="section-eyebrow">Local draft only</p>
              <h2 id="replace-script-heading">Replace your edited batch script?</h2>
              <p>Loading <code>{pendingRemoteScript.path}</code> replaces the current browser-local draft. The remote file will remain unchanged.</p>
              <div className="job-action-buttons">
                <button className="button button--secondary" type="button" onClick={() => setPendingRemoteScript(null)}>Keep current draft</button>
                <button className="button button--primary" type="button" onClick={() => { updateDraft("script", pendingRemoteScript.content); setPendingRemoteScript(null); }}>Replace local draft</button>
              </div>
            </section>
          ) : null}

          <section
            className="job-action-card"
            aria-labelledby="job-resources-heading"
          >
            <div className="job-action-card__header">
              <p className="section-eyebrow">Resources</p>
              <h2 id="job-resources-heading">Scheduler request</h2>
            </div>

            <div className="job-form-grid">
              <div className="job-form-field job-form-field--wide">
                <label htmlFor="submit-job-partition">Partition</label>
                <input
                  id="submit-job-partition"
                  name="partition"
                  value={draft.partition}
                  maxLength={100}
                  autoComplete="off"
                  placeholder="Use the cluster default"
                  onChange={(event) =>
                    updateDraft("partition", event.target.value)
                  }
                />
                <p className="job-form-field__hint">Optional</p>
              </div>

              <NumberField
                id="submit-job-nodes"
                label="Nodes"
                name="nodes"
                min={1}
                max={128}
                value={draft.nodes}
                onChange={(value) => updateDraft("nodes", value)}
              />
              <NumberField
                id="submit-job-cpus"
                label="CPUs per task"
                name="cpus_per_task"
                min={1}
                max={1024}
                value={draft.cpusPerTask}
                onChange={(value) => updateDraft("cpusPerTask", value)}
              />
              <NumberField
                id="submit-job-memory"
                label="Memory per node (MiB)"
                name="memory_mb"
                min={1}
                max={16777216}
                value={draft.memoryMb}
                required={false}
                hint="Optional"
                onChange={(value) => updateDraft("memoryMb", value)}
              />
              <NumberField
                id="submit-job-time"
                label="Time limit (minutes)"
                name="time_limit_minutes"
                min={1}
                max={525600}
                value={draft.timeLimitMinutes}
                onChange={(value) => updateDraft("timeLimitMinutes", value)}
              />
              <NumberField
                id="submit-job-gpus"
                label="GPUs per node"
                name="gpus_per_node"
                min={0}
                max={64}
                value={draft.gpusPerNode}
                onChange={(value) => updateDraft("gpusPerNode", value)}
              />
            </div>
          </section>

          <div className="job-action-form__footer">
            <p>
              The next step is review only. It will not contact Slurm.
            </p>
            <button
              className="button button--primary"
              type="submit"
              disabled={!selectedClusterId}
            >
              Review job request
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

function safeNumber(value: string): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.max(0, parsed) : 0;
}

function NumberField({
  id,
  label,
  name,
  min,
  max,
  value,
  onChange,
  required = true,
  hint,
}: {
  id: string;
  label: string;
  name: string;
  min: number;
  max: number;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  hint?: string;
}) {
  return (
    <div className="job-form-field">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        name={name}
        type="number"
        min={min}
        max={max}
        step={1}
        value={value}
        required={required}
        inputMode="numeric"
        onChange={(event) => onChange(event.target.value)}
      />
      {hint ? <p className="job-form-field__hint">{hint}</p> : null}
    </div>
  );
}

function JobSubmissionReview({
  submission,
  clusterName,
  error,
  isPending,
  onEdit,
  onConfirm,
}: {
  submission: SubmitJobRequest;
  clusterName: string;
  error: Error | null;
  isPending: boolean;
  onEdit: () => void;
  onConfirm: () => void;
}) {
  return (
    <section className="job-review" aria-labelledby="job-review-heading">
      <div className="job-review__header">
        <div>
          <p className="section-eyebrow">Confirmation required</p>
          <h2 id="job-review-heading">Review before submitting</h2>
          <p>
            Confirm this exact request for <strong>{clusterName}</strong>.
          </p>
        </div>
        <span className="job-review__not-submitted">Not submitted</span>
      </div>

      <dl className="job-review__resources">
        <ReviewValue label="Job name" value={submission.job_name} />
        <ReviewValue
          label="Partition"
          value={submission.partition ?? "Cluster default"}
        />
        <ReviewValue label="Nodes" value={submission.nodes} />
        <ReviewValue label="CPUs per task" value={submission.cpus_per_task} />
        <ReviewValue
          label="Memory"
          value={
            submission.memory_mb === null
              ? "Cluster default"
              : `${submission.memory_mb.toLocaleString()} MiB`
          }
        />
        <ReviewValue
          label="Time limit"
          value={`${submission.time_limit_minutes.toLocaleString()} minutes`}
        />
        <ReviewValue
          label="GPUs per node"
          value={submission.gpus_per_node}
        />
      </dl>

      <div className="job-review__script">
        <h3>Batch script</h3>
        <pre>{submission.script}</pre>
      </div>

      {error ? (
        <div className="job-action-feedback job-action-feedback--error" role="alert">
          <strong>Job was not submitted.</strong>
          <p>{error.message}</p>
        </div>
      ) : null}

      <div className="job-review__confirmation">
        <p>
          Clicking confirm sends this script and resource request to Slurm.
        </p>
        <div className="job-action-buttons">
          <button
            className="button button--secondary"
            type="button"
            disabled={isPending}
            onClick={onEdit}
          >
            Edit request
          </button>
          <button
            className="button button--primary"
            type="button"
            disabled={isPending}
            onClick={onConfirm}
          >
            {isPending ? "Submitting job…" : "Confirm and submit job"}
          </button>
        </div>
      </div>
    </section>
  );
}

function ReviewValue({
  label,
  value,
}: {
  label: string;
  value: string | number;
}) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
