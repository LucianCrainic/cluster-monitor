import { createContext } from "react";

import type { Cluster } from "../types/api";

export interface ClusterContextValue {
  clusters: Cluster[];
  selectedCluster: Cluster | null;
  selectedClusterId: string | null;
  selectCluster: (clusterId: string) => void;
  isLoading: boolean;
  isFetching: boolean;
  error: Error | null;
  refetch: () => void;
}

export const ClusterContext = createContext<ClusterContextValue | null>(null);
