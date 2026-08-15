import type { ClusterTopology, Node, Partition } from "../types/api";
import { formatMemory } from "../utils/format";
import { maxGpuCount } from "../utils/resources";

export interface ResourceRequestDraft {
  nodes: number;
  cpusPerNode: number;
  memoryMb: number | null;
  gpusPerNode: number;
  timeMinutes: number;
}

export function PartitionCards({
  topology,
  selectedPartition,
  request,
  onSelect,
  compact = false,
}: {
  topology: ClusterTopology;
  selectedPartition?: string | undefined;
  request?: ResourceRequestDraft;
  onSelect?: (partition: Partition) => void;
  compact?: boolean;
}) {
  return (
    <div className={`partition-grid${compact ? " partition-grid--compact" : ""}`}>
      {topology.partitions.map((partition) => {
        const nodes = topology.nodes.filter((node) =>
          node.partition_names?.includes(partition.name),
        );
        const warnings = request
          ? partitionCompatibility(partition, nodes, request)
          : [];
        const content = (
          <>
            <div className="partition-card__heading">
              <div>
                <strong>{partition.name}</strong>
                {partition.is_default ? <span>Default</span> : null}
              </div>
              <span
                className={`partition-card__availability${partition.availability ? " is-up" : " is-down"}`}
              >
                {partition.state}
              </span>
            </div>
            <div className="partition-card__node-bar" aria-label={`${partition.idle_node_count} idle, ${partition.allocated_node_count} allocated, ${partition.other_node_count} other nodes`}>
              <span
                className="is-idle"
                style={{ flexGrow: Math.max(partition.idle_node_count, 0.15) }}
              />
              <span
                className="is-allocated"
                style={{ flexGrow: Math.max(partition.allocated_node_count, 0.15) }}
              />
              <span
                className="is-other"
                style={{ flexGrow: Math.max(partition.other_node_count, 0.15) }}
              />
            </div>
            <dl className="partition-card__metrics">
              <Metric label="Nodes" value={`${partition.idle_node_count} idle / ${partition.node_count}`} />
              <Metric label="CPUs" value={sum(nodes, "cpu_count").toLocaleString()} />
              <Metric label="Memory" value={formatMemory(sum(nodes, "memory_mb"))} />
              <Metric label="Time limit" value={partition.time_limit ?? "Policy default"} />
              {!compact ? (
                <>
                  <Metric label="QoS" value={partition.qos?.join(", ") || "Default"} />
                  <Metric
                    label="Node limit"
                    value={limitRange(partition.minimum_nodes, partition.maximum_nodes)}
                  />
                </>
              ) : null}
            </dl>
            {warnings.length > 0 ? (
              <ul className="partition-card__warnings" aria-label="Compatibility warnings">
                {warnings.map((warning) => <li key={warning}>{warning}</li>)}
              </ul>
            ) : request ? (
              <p className="partition-card__compatible">Compatible with this request</p>
            ) : null}
          </>
        );

        return onSelect ? (
          <button
            className={`partition-card partition-card--selectable${selectedPartition === partition.name ? " is-selected" : ""}`}
            type="button"
            key={partition.name}
            aria-pressed={selectedPartition === partition.name}
            onClick={() => onSelect(partition)}
          >
            {content}
          </button>
        ) : (
          <article className="partition-card" key={partition.name}>
            {content}
          </article>
        );
      })}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function sum(nodes: Node[], field: "cpu_count" | "memory_mb") {
  return nodes.reduce((total, node) => total + node[field], 0);
}

function limitRange(minimum?: number | null, maximum?: number | null) {
  if (minimum == null && maximum == null) return "Policy default";
  if (minimum != null && maximum != null) return `${minimum}–${maximum}`;
  return minimum != null ? `At least ${minimum}` : `Up to ${maximum}`;
}

function partitionCompatibility(
  partition: Partition,
  nodes: Node[],
  request: ResourceRequestDraft,
): string[] {
  const warnings: string[] = [];
  if (!partition.availability) warnings.push("Partition is not currently available.");
  if (partition.minimum_nodes != null && request.nodes < partition.minimum_nodes) {
    warnings.push(`Requires at least ${partition.minimum_nodes} nodes.`);
  }
  if (partition.maximum_nodes != null && request.nodes > partition.maximum_nodes) {
    warnings.push(`Allows at most ${partition.maximum_nodes} nodes.`);
  }
  if (
    partition.maximum_cpus_per_node != null &&
    request.cpusPerNode > partition.maximum_cpus_per_node
  ) {
    warnings.push(`Allows at most ${partition.maximum_cpus_per_node} CPUs per node.`);
  }
  if (
    partition.maximum_time_minutes != null &&
    request.timeMinutes > partition.maximum_time_minutes
  ) {
    warnings.push(`Allows at most ${partition.maximum_time_minutes} minutes.`);
  }

  const eligibleNodes = nodes.filter((node) => {
    if (["down", "drained"].includes(node.state)) return false;
    const freeCpus = Math.max(0, node.cpu_count - node.allocated_cpus);
    const availableMemory = node.free_memory_mb ?? Math.max(
      0,
      node.memory_mb - (node.allocated_memory_mb ?? 0),
    );
    return (
      freeCpus >= request.cpusPerNode &&
      (request.memoryMb == null || availableMemory >= request.memoryMb) &&
      maxGpuCount(node) >= request.gpusPerNode
    );
  });
  if (request.nodes > eligibleNodes.length) {
    warnings.push(
      `Only ${eligibleNodes.length} node${eligibleNodes.length === 1 ? "" : "s"} currently match the request.`,
    );
  }
  return warnings;
}
