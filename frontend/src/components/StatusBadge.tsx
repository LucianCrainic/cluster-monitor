import type { ConnectionStatus, JobState } from "../types/api";
import { getJobStateGroup, getJobStateLabel } from "../utils/jobs";
import { titleCase } from "../utils/format";

interface BadgeProps {
  label: string;
  tone: "positive" | "info" | "warning" | "danger" | "neutral";
  context: string;
}

function Badge({ label, tone, context }: BadgeProps) {
  return (
    <span className={`status-badge status-badge--${tone}`} aria-label={`${context}: ${label}`}>
      <span className="status-badge__dot" aria-hidden="true" />
      {label}
    </span>
  );
}

export function ConnectionBadge({
  status,
}: {
  status: ConnectionStatus;
}) {
  const normalized = status.toLowerCase();
  const tone =
    normalized === "connected"
      ? "positive"
      : normalized === "unknown"
        ? "neutral"
        : "danger";

  return (
    <Badge label={titleCase(normalized)} tone={tone} context="Connection" />
  );
}

export function JobStateBadge({ state }: { state: JobState }) {
  const group = getJobStateGroup(state);
  const tone =
    group === "running"
      ? "info"
      : group === "pending"
        ? "warning"
        : group === "completed"
          ? "positive"
          : group === "failed"
            ? "danger"
            : "neutral";

  return <Badge label={getJobStateLabel(state)} tone={tone} context="Job state" />;
}
