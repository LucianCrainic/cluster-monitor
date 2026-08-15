import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { SubmitJobRequest } from "../types/api";
import { api } from "./client";
import { queryKeys } from "./queryKeys";

const DEFAULT_REFRESH_SECONDS = {
  overview_seconds: 10,
  jobs_seconds: 10,
  nodes_seconds: 30,
  partitions_seconds: 30,
  history_seconds: 60,
} as const;

export function useSettingsQuery() {
  return useQuery({
    queryKey: queryKeys.settings,
    queryFn: ({ signal }) => api.getSettings(signal),
    staleTime: Number.POSITIVE_INFINITY,
    retry: false,
  });
}

export function useRefreshSettings() {
  const settingsQuery = useSettingsQuery();
  return {
    ...DEFAULT_REFRESH_SECONDS,
    ...settingsQuery.data?.refresh,
  };
}

export function useClustersQuery() {
  return useQuery({
    queryKey: queryKeys.clusters,
    queryFn: ({ signal }) => api.getClusters(signal),
    refetchInterval: 30_000,
  });
}

export function useOverviewQuery(clusterId: string | null) {
  const refresh = useRefreshSettings();

  return useQuery({
    queryKey: queryKeys.overview(clusterId ?? ""),
    queryFn: ({ signal }) => api.getOverview(clusterId ?? "", signal),
    enabled: Boolean(clusterId),
    refetchInterval: refresh.overview_seconds * 1000,
  });
}

export function useTopologyQuery(clusterId: string | null) {
  const refresh = useRefreshSettings();

  return useQuery({
    queryKey: queryKeys.topology(clusterId ?? ""),
    queryFn: ({ signal }) => api.getTopology(clusterId ?? "", signal),
    enabled: Boolean(clusterId),
    refetchInterval: refresh.nodes_seconds * 1000,
  });
}

export function useJobsQuery(clusterId: string | null) {
  const refresh = useRefreshSettings();

  return useQuery({
    queryKey: queryKeys.jobs(clusterId ?? ""),
    queryFn: ({ signal }) => api.getJobs(clusterId ?? "", signal),
    enabled: Boolean(clusterId),
    refetchInterval: refresh.jobs_seconds * 1000,
  });
}

export function useHistoryQuery(clusterId: string | null) {
  const refresh = useRefreshSettings();

  return useQuery({
    queryKey: queryKeys.history(clusterId ?? ""),
    queryFn: ({ signal }) => api.getHistory(clusterId ?? "", signal),
    enabled: Boolean(clusterId),
    refetchInterval: refresh.history_seconds * 1000,
  });
}

export function useJobQuery(clusterId: string | null, jobId: string | null) {
  const refresh = useRefreshSettings();

  return useQuery({
    queryKey: queryKeys.job(clusterId ?? "", jobId ?? ""),
    queryFn: ({ signal }) =>
      api.getJob(clusterId ?? "", jobId ?? "", signal),
    enabled: Boolean(clusterId && jobId),
    refetchInterval: refresh.jobs_seconds * 1000,
  });
}

export function useSubmitJobMutation(clusterId: string | null) {
  const queryClient = useQueryClient();

  return useMutation({
    retry: false,
    mutationFn: (submission: SubmitJobRequest) => {
      if (!clusterId) {
        throw new Error("Select a cluster before submitting a job.");
      }
      return api.submitJob(clusterId, submission);
    },
    onSuccess: async () => {
      if (!clusterId) {
        return;
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.jobs(clusterId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.history(clusterId) }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.overview(clusterId),
        }),
        queryClient.invalidateQueries({ queryKey: queryKeys.clusters }),
      ]);
    },
  });
}

export function useCancelJobMutation(
  clusterId: string | null,
  jobId: string | null,
) {
  const queryClient = useQueryClient();

  return useMutation({
    retry: false,
    mutationFn: () => {
      if (!clusterId || !jobId) {
        throw new Error("The cluster and job must be selected before cancellation.");
      }
      return api.cancelJob(clusterId, jobId);
    },
    onSuccess: async () => {
      if (!clusterId || !jobId) {
        return;
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.jobs(clusterId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.history(clusterId) }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.job(clusterId, jobId),
        }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.overview(clusterId),
        }),
        queryClient.invalidateQueries({ queryKey: queryKeys.clusters }),
      ]);
    },
  });
}
