import { NavLink, Outlet } from "react-router";

import { useCluster } from "../context/useCluster";
import { ClusterSelector } from "./ClusterSelector";
import { EmptyState, ErrorState, LoadingState } from "./PageState";
import { ThemeToggle } from "./ThemeToggle";

const navigation = [
  { to: "/", label: "Overview", icon: "◫", end: true },
  { to: "/jobs", label: "Jobs", icon: "≡", end: false },
  { to: "/history", label: "History", icon: "↶", end: true },
  { to: "/topology", label: "Topology", icon: "⌘", end: true },
  { to: "/files", label: "Files", icon: "▤", end: true },
] as const;

export function AppShell() {
  const { clusters, selectedCluster, isLoading, error, refetch } = useCluster();
  const actionsEnabled = selectedCluster?.job_actions_enabled === true;
  const filesEnabled = selectedCluster?.file_browser_enabled === true;

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <aside className="sidebar">
        <div className="brand">
          <span className="brand__mark" aria-hidden="true">
            cm
          </span>
          <span>
            <strong>Cluster Monitor</strong>
            <small>Local console</small>
          </span>
        </div>

        <nav className="primary-nav" aria-label="Primary navigation">
          <p className="primary-nav__eyebrow">Monitor</p>
          <ul>
            {navigation.map((item) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    `primary-nav__link${isActive ? " is-active" : ""}`
                  }
                >
                  <span aria-hidden="true">{item.icon}</span>
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>

        <div className="sidebar__footer">
          <span className="cluster-action-status">
            <span aria-hidden="true">●</span>
            {actionsEnabled ? "Job actions enabled" : "Monitoring only"}
          </span>
          <span className="cluster-action-status">
            <span aria-hidden="true">●</span>
            {filesEnabled ? "Read-only files enabled" : "Files disabled"}
          </span>
          <small>SSH credentials stay on this computer.</small>
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div className="topbar__context">
            <span className="topbar__eyebrow">Workspace</span>
            <strong>Slurm operations</strong>
          </div>
          <div className="topbar__actions">
            <ClusterSelector />
            <ThemeToggle />
          </div>
        </header>

        <main id="main-content" className="main-content" tabIndex={-1}>
          {isLoading ? (
            <LoadingState label="Loading configured clusters…" />
          ) : error ? (
            <ErrorState
              error={error}
              onRetry={refetch}
              title="Cannot reach the local service"
            />
          ) : clusters.length === 0 ? (
            <EmptyState
              title="No clusters configured"
              description="Add a mock or SSH cluster to the local configuration, then restart the backend."
            />
          ) : (
            <Outlet />
          )}
        </main>
      </div>
    </div>
  );
}
