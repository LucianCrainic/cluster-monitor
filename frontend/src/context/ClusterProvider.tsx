import { useMemo, useState, type PropsWithChildren } from "react";

import { useClustersQuery, useSettingsQuery } from "../api/queries";
import { ClusterContext } from "./clusterContext";

export function ClusterProvider({ children }: PropsWithChildren) {
  const clustersQuery = useClustersQuery();
  const settingsQuery = useSettingsQuery();
  const [chosenClusterId, setChosenClusterId] = useState<string | null>(null);
  const refetchClusters = clustersQuery.refetch;

  const clusters = useMemo(
    () => clustersQuery.data ?? [],
    [clustersQuery.data],
  );
  const preferredClusterId =
    chosenClusterId ?? settingsQuery.data?.default_cluster_id ?? null;
  const selectedCluster =
    clusters.find((cluster) => cluster.id === preferredClusterId) ??
    clusters[0] ??
    null;

  const value = useMemo(
    () => ({
      clusters,
      selectedCluster,
      selectedClusterId: selectedCluster?.id ?? null,
      selectCluster: setChosenClusterId,
      isLoading: clustersQuery.isLoading,
      isFetching: clustersQuery.isFetching,
      error: clustersQuery.error,
      refetch: () => {
        void refetchClusters();
      },
    }),
    [
      clusters,
      clustersQuery.error,
      clustersQuery.isFetching,
      clustersQuery.isLoading,
      refetchClusters,
      selectedCluster,
    ],
  );

  return (
    <ClusterContext.Provider value={value}>
      {children}
    </ClusterContext.Provider>
  );
}
