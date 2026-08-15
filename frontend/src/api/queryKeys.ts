export const queryKeys = {
  settings: ["settings"] as const,
  clusters: ["clusters"] as const,
  overview: (clusterId: string) => ["clusters", clusterId, "overview"] as const,
  topology: (clusterId: string) => ["clusters", clusterId, "topology"] as const,
  jobs: (clusterId: string) => ["clusters", clusterId, "jobs"] as const,
  history: (clusterId: string) => ["clusters", clusterId, "history"] as const,
  job: (clusterId: string, jobId: string) =>
    ["clusters", clusterId, "jobs", jobId] as const,
};
