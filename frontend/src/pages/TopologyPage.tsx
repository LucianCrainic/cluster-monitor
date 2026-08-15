import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";

import { useJobQuery, useTopologyQuery } from "../api/queries";
import { PartitionCards } from "../components/PartitionCards";
import { ErrorState, LoadingState } from "../components/PageState";
import { RefreshButton } from "../components/RefreshButton";
import { useCluster } from "../context/useCluster";
import type { ClusterTopology, Node, NodeState } from "../types/api";
import { formatDateTime, formatMemory, titleCase } from "../utils/format";
import { maxGpuCount } from "../utils/resources";

const NODE_STATES: NodeState[] = [
  "idle", "allocated", "mixed", "completing", "drained", "down", "unknown",
];

export function TopologyPage() {
  const { selectedCluster, selectedClusterId } = useCluster();
  const [searchParams] = useSearchParams();
  const highlightedJobId = searchParams.get("job");
  const topologyQuery = useTopologyQuery(selectedClusterId);
  const jobQuery = useJobQuery(selectedClusterId, highlightedJobId);
  const [partitionFilter, setPartitionFilter] = useState("all");
  const [stateFilter, setStateFilter] = useState("all");
  const [gpuOnly, setGpuOnly] = useState(false);
  const [nameFilter, setNameFilter] = useState("");
  const [selectedNodeName, setSelectedNodeName] = useState<string | null>(null);
  const [view, setView] = useState<"resources" | "physical">("resources");

  const topology = topologyQuery.data;
  const allocatedNodes = useMemo(
    () => new Set(jobQuery.data?.node_list ?? []),
    [jobQuery.data?.node_list],
  );
  const filteredNodes = useMemo(() => {
    if (!topology) return [];
    const needle = nameFilter.trim().toLocaleLowerCase();
    return topology.nodes.filter((node) => (
      (partitionFilter === "all" || node.partition_names?.includes(partitionFilter)) &&
      (stateFilter === "all" || node.state === stateFilter) &&
      (!gpuOnly || maxGpuCount(node) > 0) &&
      (!needle || node.name.toLocaleLowerCase().includes(needle))
    ));
  }, [gpuOnly, nameFilter, partitionFilter, stateFilter, topology]);
  const selectedNode = topology?.nodes.find((node) => node.name === selectedNodeName) ?? null;
  const physicalAvailable = Boolean(topology && topology.kind !== "flat" && topology.groups?.length);

  if (topologyQuery.isLoading) {
    return <div className="page"><LoadingState label="Loading cluster topology…" variant="detail" /></div>;
  }
  if (topologyQuery.error) {
    return (
      <div className="page">
        <ErrorState error={topologyQuery.error} onRetry={() => void topologyQuery.refetch()} title="Topology unavailable" />
      </div>
    );
  }
  if (!topology) return null;

  return (
    <div className="page topology-page">
      <header className="page-header">
        <div>
          <p className="page-header__eyebrow">Resource explorer</p>
          <h1>Cluster topology</h1>
          <p>
            Live Slurm resources for <strong>{selectedCluster?.name ?? topology.cluster_id}</strong>.
            {highlightedJobId ? <> Highlighting allocation for job <strong>{highlightedJobId}</strong>.</> : null}
          </p>
        </div>
        <div className="page-header__actions">
          {highlightedJobId ? <Link className="button button--secondary" to={`/jobs/${encodeURIComponent(highlightedJobId)}`}>Back to job</Link> : null}
          <RefreshButton isRefreshing={topologyQuery.isFetching} onRefresh={() => void topologyQuery.refetch()} />
        </div>
      </header>

      <div className="topology-view-tabs" role="tablist" aria-label="Topology view">
        <button type="button" role="tab" aria-selected={view === "resources"} onClick={() => setView("resources")}>Resource map</button>
        <button type="button" role="tab" aria-selected={view === "physical"} disabled={!physicalAvailable} onClick={() => setView("physical")}>
          Physical topology{physicalAvailable ? "" : " unavailable"}
        </button>
      </div>

      {view === "physical" && physicalAvailable ? (
        <PhysicalTopology topology={topology} selectedNodeName={selectedNodeName} onSelectNode={setSelectedNodeName} allocatedNodes={allocatedNodes} />
      ) : (
        <>
          {!physicalAvailable ? (
            <p className="topology-fallback-note">
              Slurm does not report a physical switch, block, or ring hierarchy, so this resource map is the authoritative view. No rack layout is inferred from node names.
            </p>
          ) : null}
          <section aria-labelledby="partition-map-heading">
            <div className="section-heading">
              <div><p className="section-eyebrow">Partitions</p><h2 id="partition-map-heading">Capacity and policy</h2></div>
              <span>Captured {formatDateTime(topology.captured_at)}</span>
            </div>
            <PartitionCards topology={topology} />
          </section>

          <section className="node-map" aria-labelledby="node-map-heading">
            <div className="section-heading">
              <div><p className="section-eyebrow">Nodes</p><h2 id="node-map-heading">Resource map</h2></div>
              <span>{filteredNodes.length} of {topology.nodes.length} nodes</span>
            </div>
            <div className="node-filters">
              <label>Partition<select value={partitionFilter} onChange={(event) => setPartitionFilter(event.target.value)}><option value="all">All partitions</option>{topology.partitions.map((partition) => <option key={partition.name} value={partition.name}>{partition.name}</option>)}</select></label>
              <label>State<select value={stateFilter} onChange={(event) => setStateFilter(event.target.value)}><option value="all">All states</option>{NODE_STATES.map((state) => <option key={state} value={state}>{titleCase(state)}</option>)}</select></label>
              <label>Node name<input type="search" value={nameFilter} placeholder="e.g. node124" onChange={(event) => setNameFilter(event.target.value)} /></label>
              <label className="node-filters__check"><input type="checkbox" checked={gpuOnly} onChange={(event) => setGpuOnly(event.target.checked)} /> GPU nodes only</label>
            </div>
            <div className="node-layout">
              <div className="node-grid">
                {filteredNodes.map((node) => (
                  <NodeCard
                    key={node.name}
                    node={node}
                    selected={node.name === selectedNodeName}
                    allocated={allocatedNodes.has(node.name)}
                    onSelect={() => setSelectedNodeName(node.name)}
                  />
                ))}
                {filteredNodes.length === 0 ? <p className="node-grid__empty">No nodes match these filters.</p> : null}
              </div>
              <NodeInspector node={selectedNode} allocated={selectedNode ? allocatedNodes.has(selectedNode.name) : false} />
            </div>
          </section>
        </>
      )}
    </div>
  );
}

function NodeCard({ node, selected, allocated, onSelect }: { node: Node; selected: boolean; allocated: boolean; onSelect: () => void }) {
  const cpuPercent = node.cpu_count ? Math.round(node.allocated_cpus / node.cpu_count * 100) : 0;
  return (
    <button className={`node-card state-${node.state}${selected ? " is-selected" : ""}${allocated ? " is-job-allocation" : ""}`} type="button" onClick={onSelect} aria-pressed={selected}>
      <span className="node-card__top"><strong>{node.name}</strong><span>{titleCase(node.state)}</span></span>
      <span className="node-card__partitions">{node.partition_names?.join(", ") || "No partition"}</span>
      <span className="node-card__resource"><span>CPU</span><span>{node.allocated_cpus}/{node.cpu_count}</span></span>
      <span className="node-card__meter"><span style={{ width: `${Math.min(100, cpuPercent)}%` }} /></span>
      <span className="node-card__footer"><span>{formatMemory(node.memory_mb)}</span>{maxGpuCount(node) ? <span>{maxGpuCount(node)} GPU</span> : null}</span>
      {allocated ? <span className="node-card__allocation">Selected job</span> : null}
    </button>
  );
}

function NodeInspector({ node, allocated }: { node: Node | null; allocated: boolean }) {
  if (!node) {
    return <aside className="node-inspector node-inspector--empty"><strong>Node inspector</strong><p>Select a node to inspect its Slurm metadata.</p></aside>;
  }
  const values: Array<[string, string]> = [
    ["State", node.state_raw],
    ["Partitions", node.partition_names?.join(", ") || "—"],
    ["CPUs", `${node.allocated_cpus} allocated / ${node.cpu_count} total`],
    ["CPU load", node.cpu_load == null ? "—" : node.cpu_load.toFixed(2)],
    ["Memory", `${formatMemory(node.free_memory_mb)} free / ${formatMemory(node.memory_mb)}`],
    ["Layout", node.sockets == null ? "—" : `${node.sockets} sockets × ${node.cores_per_socket ?? "?"} cores × ${node.threads_per_core ?? "?"} threads`],
    ["GRES", node.generic_resources?.join(", ") || "—"],
    ["Allocated GRES", node.allocated_generic_resources?.join(", ") || "—"],
    ["Active features", node.active_features?.join(", ") || "—"],
    ["Configured features", node.configured_features?.join(", ") || "—"],
    ["Reason", node.reason ?? "—"],
  ];
  return (
    <aside className="node-inspector">
      <div><p className="section-eyebrow">Node inspector</p><h3>{node.name}</h3>{allocated ? <span className="allocation-pill">Allocated to selected job</span> : null}</div>
      <dl>{values.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
    </aside>
  );
}

function PhysicalTopology({ topology, selectedNodeName, onSelectNode, allocatedNodes }: { topology: ClusterTopology; selectedNodeName: string | null; onSelectNode: (name: string) => void; allocatedNodes: Set<string> }) {
  const known = new Map(topology.nodes.map((node) => [node.name, node]));
  const groups = topology.groups ?? [];
  return (
    <section className="physical-topology" aria-labelledby="physical-topology-heading">
      <div className="section-heading"><div><p className="section-eyebrow">Slurm-reported hierarchy</p><h2 id="physical-topology-heading">{titleCase(topology.kind)} topology</h2></div><span>{groups.length} groups</span></div>
      <div className="physical-topology__groups">
        {groups.map((group) => (
          <article key={group.id} className="topology-group">
            <header><span aria-hidden="true">⌘</span><div><strong>{group.name}</strong><small>{titleCase(group.kind)}{group.link_speed ? ` · ${group.link_speed}` : ""}</small></div></header>
            {group.child_group_ids?.length ? <p>Links to {group.child_group_ids.map((id) => id.replace(/^\w+:/, "")).join(", ")}</p> : null}
            <div className="topology-group__nodes">
              {(group.node_names ?? []).map((name) => known.has(name) ? (
                <button key={name} type="button" className={`${selectedNodeName === name ? "is-selected" : ""}${allocatedNodes.has(name) ? " is-job-allocation" : ""}`} onClick={() => onSelectNode(name)}>{name}</button>
              ) : null)}
              {!group.node_names?.length ? <span>No direct nodes</span> : null}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
