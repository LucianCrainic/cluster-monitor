import { useMemo, useState, type CSSProperties } from "react";
import { Link, useSearchParams } from "react-router";

import { useJobQuery, useTopologyQuery } from "../api/queries";
import { Icon } from "../components/Icon";
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
const PAGE_SIZE = 480;

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
  const [presentation, setPresentation] = useState<"map" | "cards">("map");
  const [visibleLimit, setVisibleLimit] = useState(PAGE_SIZE);

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
  const visibleNodes = filteredNodes.slice(0, visibleLimit);
  const selectedNode = topology?.nodes.find((node) => node.name === selectedNodeName) ?? null;
  const physicalAvailable = Boolean(topology && topology.kind !== "flat" && topology.groups?.length);
  const summary = useMemo(() => topology ? summarizeTopology(topology) : null, [topology]);

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
  if (!topology || !summary) return null;

  const hasFilters = partitionFilter !== "all" || stateFilter !== "all" || gpuOnly || nameFilter !== "";
  const clearFilters = () => {
    setPartitionFilter("all");
    setStateFilter("all");
    setGpuOnly(false);
    setNameFilter("");
    setVisibleLimit(PAGE_SIZE);
  };

  return (
    <div className="page topology-page">
      <header className="page-header">
        <div>
          <p className="page-header__eyebrow">Resource explorer</p>
          <h1>Cluster topology</h1>
          <p>
            A scalable view of <strong>{selectedCluster?.name ?? topology.cluster_id}</strong>,
            from partition capacity down to individual nodes.
            {highlightedJobId ? <> Highlighting job <strong>{highlightedJobId}</strong>.</> : null}
          </p>
        </div>
        <div className="page-header__actions">
          {highlightedJobId ? <Link className="button button--secondary" to={`/jobs/${encodeURIComponent(highlightedJobId)}`}>Back to job</Link> : null}
          <RefreshButton isRefreshing={topologyQuery.isFetching} onRefresh={() => void topologyQuery.refetch()} />
        </div>
      </header>

      <section className="topology-summary" aria-label="Cluster resource summary">
        <TopologyMetric icon="nodes" label="Nodes" value={summary.nodes.toLocaleString()} detail={`${summary.availableNodes.toLocaleString()} schedulable`} />
        <TopologyMetric icon="cpu" label="CPU capacity" value={summary.cpus.toLocaleString()} detail={`${summary.freeCpus.toLocaleString()} currently free`} />
        <TopologyMetric icon="memory" label="Memory" value={formatMemory(summary.memoryMb)} detail={`${formatMemory(summary.freeMemoryMb)} reported free`} />
        <TopologyMetric icon="gpu" label="Accelerators" value={summary.gpuNodes.toLocaleString()} detail="GPU-equipped nodes" />
      </section>

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
              Slurm does not report a physical switch, block, or ring hierarchy. The resource map below is authoritative. No rack layout is inferred from node names.
            </p>
          ) : null}

          <section className="topology-panel" aria-labelledby="partition-map-heading">
            <div className="section-heading">
              <div><p className="section-eyebrow">Partitions</p><h2 id="partition-map-heading">Capacity and policy</h2></div>
              <span>{topology.partitions.length} partitions · captured {formatDateTime(topology.captured_at)}</span>
            </div>
            <PartitionCards topology={topology} />
          </section>

          <section className="node-map" aria-labelledby="node-map-heading">
            <div className="section-heading">
              <div><p className="section-eyebrow">Node explorer</p><h2 id="node-map-heading">Resource map</h2></div>
              <span>{filteredNodes.length.toLocaleString()} of {topology.nodes.length.toLocaleString()} nodes</span>
            </div>

            <div className="node-state-summary" aria-label="Node state summary">
              <button type="button" className={stateFilter === "all" ? "is-active" : ""} aria-pressed={stateFilter === "all"} onClick={() => { setStateFilter("all"); setVisibleLimit(PAGE_SIZE); }}>
                <span className="state-dot state-all" />All<strong>{topology.nodes.length}</strong>
              </button>
              {NODE_STATES.map((state) => {
                const count = summary.states.get(state) ?? 0;
                if (!count) return null;
                return (
                  <button key={state} type="button" className={stateFilter === state ? "is-active" : ""} aria-pressed={stateFilter === state} onClick={() => { setStateFilter(state); setVisibleLimit(PAGE_SIZE); }}>
                    <span className={`state-dot state-${state}`} />{titleCase(state)}<strong>{count}</strong>
                  </button>
                );
              })}
            </div>

            <div className="node-filters">
              <label>Partition<select value={partitionFilter} onChange={(event) => { setPartitionFilter(event.target.value); setVisibleLimit(PAGE_SIZE); }}><option value="all">All partitions</option>{topology.partitions.map((partition) => <option key={partition.name} value={partition.name}>{partition.name}</option>)}</select></label>
              <label>State<select value={stateFilter} onChange={(event) => { setStateFilter(event.target.value); setVisibleLimit(PAGE_SIZE); }}><option value="all">All states</option>{NODE_STATES.map((state) => <option key={state} value={state}>{titleCase(state)}</option>)}</select></label>
              <label>Node name<input type="search" value={nameFilter} placeholder="Search node name" onChange={(event) => { setNameFilter(event.target.value); setVisibleLimit(PAGE_SIZE); }} /></label>
              <label className="node-filters__check"><input type="checkbox" checked={gpuOnly} onChange={(event) => { setGpuOnly(event.target.checked); setVisibleLimit(PAGE_SIZE); }} /> GPU nodes only</label>
              <button className="button button--ghost" type="button" disabled={!hasFilters} onClick={clearFilters}>Clear</button>
            </div>

            <div className="node-explorer-toolbar">
              <div className="node-view-toggle" role="group" aria-label="Node presentation">
                <button type="button" aria-pressed={presentation === "map"} className={presentation === "map" ? "is-active" : ""} onClick={() => { setPresentation("map"); setVisibleLimit(PAGE_SIZE); }}><Icon name="grid" />Density map</button>
                <button type="button" aria-pressed={presentation === "cards"} className={presentation === "cards" ? "is-active" : ""} onClick={() => { setPresentation("cards"); setVisibleLimit(PAGE_SIZE); }}><Icon name="list" />Details</button>
              </div>
              <ul className="node-map-legend" aria-label="Map legend">
                <li><span className="state-dot state-idle" />Idle</li>
                <li><span className="state-dot state-allocated" />In use</li>
                <li><span className="state-dot state-drained" />Drained</li>
                <li><span className="state-dot state-down" />Down</li>
                {highlightedJobId ? <li><span className="state-dot is-job-allocation" />Job {highlightedJobId}</li> : null}
              </ul>
            </div>

            <div className="node-layout">
              <div>
                {visibleNodes.length === 0 ? (
                  <p className="node-grid__empty">No nodes match these filters.</p>
                ) : presentation === "map" ? (
                  <div className="node-density-map">
                    {visibleNodes.map((node) => (
                      <NodeDot
                        key={node.name}
                        node={node}
                        selected={node.name === selectedNodeName}
                        allocated={allocatedNodes.has(node.name)}
                        onSelect={() => setSelectedNodeName(node.name)}
                      />
                    ))}
                  </div>
                ) : (
                  <div className="node-grid">
                    {visibleNodes.map((node) => (
                      <NodeCard
                        key={node.name}
                        node={node}
                        selected={node.name === selectedNodeName}
                        allocated={allocatedNodes.has(node.name)}
                        onSelect={() => setSelectedNodeName(node.name)}
                      />
                    ))}
                  </div>
                )}
                {visibleNodes.length < filteredNodes.length ? (
                  <div className="node-map__more">
                    <span>Showing {visibleNodes.length.toLocaleString()} of {filteredNodes.length.toLocaleString()} matching nodes.</span>
                    <button className="button button--secondary" type="button" onClick={() => setVisibleLimit((value) => value + PAGE_SIZE)}>Show more nodes</button>
                  </div>
                ) : null}
              </div>
              <NodeInspector node={selectedNode} allocated={selectedNode ? allocatedNodes.has(selectedNode.name) : false} />
            </div>
          </section>
        </>
      )}
    </div>
  );
}

function TopologyMetric({ icon, label, value, detail }: { icon: "nodes" | "cpu" | "memory" | "gpu"; label: string; value: string; detail: string }) {
  return <article><span><Icon name={icon} /></span><div><small>{label}</small><strong>{value}</strong><em>{detail}</em></div></article>;
}

function NodeDot({ node, selected, allocated, onSelect }: { node: Node; selected: boolean; allocated: boolean; onSelect: () => void }) {
  const cpuPercent = node.cpu_count ? Math.round((node.allocated_cpus / node.cpu_count) * 100) : 0;
  const description = `${node.name}, ${titleCase(node.state)}, ${node.allocated_cpus} of ${node.cpu_count} CPUs allocated${allocated ? ", selected job allocation" : ""}`;
  return (
    <button
      className={`node-dot state-${node.state}${selected ? " is-selected" : ""}${allocated ? " is-job-allocation" : ""}`}
      type="button"
      aria-label={description}
      aria-pressed={selected}
      title={description}
      style={{ "--cpu-use": `${cpuPercent}%` } as CSSProperties}
      onClick={onSelect}
    >
      {allocated ? <span className="sr-only">Selected job</span> : null}
    </button>
  );
}

function NodeCard({ node, selected, allocated, onSelect }: { node: Node; selected: boolean; allocated: boolean; onSelect: () => void }) {
  const cpuPercent = node.cpu_count ? Math.round((node.allocated_cpus / node.cpu_count) * 100) : 0;
  return (
    <button className={`node-card state-${node.state}${selected ? " is-selected" : ""}${allocated ? " is-job-allocation" : ""}`} type="button" onClick={onSelect} aria-pressed={selected}>
      <span className="node-card__top"><strong>{node.name}</strong><span>{titleCase(node.state)}</span></span>
      <span className="node-card__partitions">{node.partition_names?.join(", ") || "No partition"}</span>
      <span className="node-card__resource"><span>CPU use</span><span>{node.allocated_cpus}/{node.cpu_count}</span></span>
      <span className="node-card__meter"><span style={{ width: `${Math.min(100, cpuPercent)}%` }} /></span>
      <span className="node-card__footer"><span>{formatMemory(node.free_memory_mb)} free</span>{maxGpuCount(node) ? <span>{maxGpuCount(node)} GPU</span> : null}</span>
      {allocated ? <span className="node-card__allocation">Selected job</span> : null}
    </button>
  );
}

function NodeInspector({ node, allocated }: { node: Node | null; allocated: boolean }) {
  if (!node) {
    return <aside className="node-inspector node-inspector--empty"><span className="node-inspector__glyph"><Icon name="nodes" /></span><strong>Node inspector</strong><p>Select any tile to inspect resource and Slurm metadata.</p></aside>;
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
  const cpuPercent = node.cpu_count ? Math.round((node.allocated_cpus / node.cpu_count) * 100) : 0;
  return (
    <aside className="node-inspector">
      <div className="node-inspector__header">
        <div><p className="section-eyebrow">Node inspector</p><h3>{node.name}</h3></div>
        <span className={`node-health state-${node.state}`}>{titleCase(node.state)}</span>
      </div>
      {allocated ? <span className="allocation-pill">Allocated to selected job</span> : null}
      <div className="node-inspector__meter"><span><i style={{ width: `${Math.min(100, cpuPercent)}%` }} /></span><small>{cpuPercent}% CPUs allocated</small></div>
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
            <header><span aria-hidden="true"><Icon name="topology" /></span><div><strong>{group.name}</strong><small>{titleCase(group.kind)}{group.link_speed ? ` · ${group.link_speed}` : ""}</small></div></header>
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

function summarizeTopology(topology: ClusterTopology) {
  const states = new Map<NodeState, number>();
  let cpus = 0;
  let freeCpus = 0;
  let memoryMb = 0;
  let freeMemoryMb = 0;
  let gpuNodes = 0;
  for (const node of topology.nodes) {
    states.set(node.state, (states.get(node.state) ?? 0) + 1);
    cpus += node.cpu_count;
    freeCpus += Math.max(0, node.cpu_count - node.allocated_cpus);
    memoryMb += node.memory_mb;
    freeMemoryMb += node.free_memory_mb ?? Math.max(0, node.memory_mb - (node.allocated_memory_mb ?? 0));
    if (maxGpuCount(node) > 0) gpuNodes += 1;
  }
  return {
    nodes: topology.nodes.length,
    availableNodes: (states.get("idle") ?? 0) + (states.get("mixed") ?? 0),
    cpus,
    freeCpus,
    memoryMb,
    freeMemoryMb,
    gpuNodes,
    states,
  };
}
