import { RemoteFileBrowser } from "../components/RemoteFileBrowser";
import { useCluster } from "../context/useCluster";

export function FilesPage() {
  const { selectedCluster, selectedClusterId } = useCluster();
  if (!selectedClusterId) return null;
  if (!selectedCluster?.file_browser_enabled) {
    return (
      <div className="page">
        <header className="page-header"><div><p className="page-header__eyebrow">Remote workspace</p><h1>Files</h1></div></header>
        <section className="job-action-feedback"><h2>Read-only file browsing is disabled</h2><p>Enable it explicitly in this cluster&apos;s local configuration to inspect SSH-visible files.</p></section>
      </div>
    );
  }
  return (
    <div className="page files-page">
      <header className="page-header">
        <div><p className="page-header__eyebrow">Remote workspace</p><h1>Files</h1><p>Browse and inspect files as the remote SSH identity. This workspace cannot create, edit, rename, upload, or delete anything.</p></div>
        <span className="read-only-badge">Read only</span>
      </header>
      <RemoteFileBrowser clusterId={selectedClusterId} />
    </div>
  );
}
