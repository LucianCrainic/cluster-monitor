import type { ClusterOverview } from "../types/api";

export interface CapacitySegment {
  key: "idle" | "allocated" | "unavailable" | "other";
  label: string;
  value: number;
  percentage: number;
}

export function getCapacitySegments(
  overview: ClusterOverview,
): CapacitySegment[] {
  const known =
    overview.idle_nodes +
    overview.allocated_nodes +
    overview.unavailable_nodes;
  const other = Math.max(overview.total_nodes - known, 0);
  const total = Math.max(overview.total_nodes, 1);

  const segments: Omit<CapacitySegment, "percentage">[] = [
    { key: "idle", label: "Idle", value: overview.idle_nodes },
    {
      key: "allocated",
      label: "Allocated",
      value: overview.allocated_nodes,
    },
    {
      key: "unavailable",
      label: "Unavailable",
      value: overview.unavailable_nodes,
    },
    { key: "other", label: "Other", value: other },
  ];

  return segments
    .filter((segment) => segment.value > 0)
    .map((segment) => ({
      ...segment,
      percentage: (segment.value / total) * 100,
    }));
}
