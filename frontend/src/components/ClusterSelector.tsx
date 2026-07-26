import { useCluster } from "../context/useCluster";
import { ConnectionBadge } from "./StatusBadge";

export function ClusterSelector() {
  const {
    clusters,
    selectedCluster,
    selectedClusterId,
    selectCluster,
    isFetching,
  } = useCluster();

  if (!selectedCluster) {
    return null;
  }

  return (
    <div className="cluster-control">
      <label className="cluster-control__label" htmlFor="cluster-selector">
        Active cluster
      </label>
      <div className="cluster-control__row">
        <select
          id="cluster-selector"
          className="cluster-control__select"
          value={selectedClusterId ?? ""}
          onChange={(event) => selectCluster(event.target.value)}
          aria-describedby="cluster-connection-status"
        >
          {clusters.map((cluster) => (
            <option key={cluster.id} value={cluster.id}>
              {cluster.name}
            </option>
          ))}
        </select>
        <span
          id="cluster-connection-status"
          className={isFetching ? "is-refreshing" : undefined}
        >
          <ConnectionBadge status={selectedCluster.connection_status} />
        </span>
      </div>
    </div>
  );
}
