import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router";

import { useCluster } from "../context/useCluster";
import { ClusterSelector } from "./ClusterSelector";
import { Icon, type IconName } from "./Icon";
import { EmptyState, ErrorState, LoadingState } from "./PageState";
import { ThemeToggle } from "./ThemeToggle";

const navigation = [
  { to: "/", label: "Overview", icon: "overview", end: true },
  { to: "/jobs", label: "Jobs", icon: "jobs", end: false },
  { to: "/history", label: "History", icon: "history", end: true },
  { to: "/topology", label: "Topology", icon: "topology", end: true },
  { to: "/files", label: "Files", icon: "files", end: true },
] satisfies ReadonlyArray<{ to: string; label: string; icon: IconName; end: boolean }>;

const SIDEBAR_STORAGE_KEY = "cluster-monitor-sidebar-collapsed";

function readSidebarPreference() {
  try {
    return window.localStorage.getItem(SIDEBAR_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

export function AppShell() {
  const { clusters, selectedCluster, isLoading, error, refetch } = useCluster();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(readSidebarPreference);
  const actionsEnabled = selectedCluster?.job_actions_enabled === true;
  const filesEnabled = selectedCluster?.file_browser_enabled === true;

  useEffect(() => {
    try {
      window.localStorage.setItem(SIDEBAR_STORAGE_KEY, String(sidebarCollapsed));
    } catch {
      // Storage can be unavailable in hardened browser contexts.
    }
  }, [sidebarCollapsed]);

  return (
    <div className={`app-shell${sidebarCollapsed ? " app-shell--collapsed" : ""}`}>
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <aside className="sidebar">
        <div className="sidebar__header">
          <div className="brand">
            <img className="brand__mark" src="/cm-mark.svg" alt="" />
            <span className="brand__copy">
              <strong>Cluster Monitor</strong>
              <small>Local console</small>
            </span>
          </div>
          <button
            className="sidebar__collapse"
            type="button"
            aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            onClick={() => setSidebarCollapsed((value) => !value)}
          >
            <Icon name={sidebarCollapsed ? "expand" : "collapse"} />
          </button>
        </div>

        <nav className="primary-nav" aria-label="Primary navigation">
          <p className="primary-nav__eyebrow">Monitor</p>
          <ul>
            {navigation.map((item) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  end={item.end}
                  title={sidebarCollapsed ? item.label : undefined}
                  className={({ isActive }) =>
                    `primary-nav__link${isActive ? " is-active" : ""}`
                  }
                >
                  <span className="primary-nav__icon"><Icon name={item.icon} /></span>
                  <span className="primary-nav__label">{item.label}</span>
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
