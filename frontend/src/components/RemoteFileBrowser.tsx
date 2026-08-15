import { cpp } from "@codemirror/lang-cpp";
import { css } from "@codemirror/lang-css";
import { html } from "@codemirror/lang-html";
import { javascript } from "@codemirror/lang-javascript";
import { json } from "@codemirror/lang-json";
import { markdown } from "@codemirror/lang-markdown";
import { python } from "@codemirror/lang-python";
import { yaml } from "@codemirror/lang-yaml";
import { StreamLanguage, type LanguageSupport } from "@codemirror/language";
import { shell } from "@codemirror/legacy-modes/mode/shell";
import { EditorView } from "@codemirror/view";
import CodeMirror from "@uiw/react-codemirror";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import type {
  RemoteDirectory,
  RemoteFileEntry,
  RemoteFilePreview,
} from "../types/api";
import { formatDateTime } from "../utils/format";
import { quotePosixPath } from "../utils/paths";

interface RemoteFileBrowserProps {
  clusterId: string;
  compact?: boolean;
  onInsertPath?: (quotedPath: string, path: string) => void;
  onUseAsScript?: (content: string, path: string) => void;
}

export function RemoteFileBrowser({
  clusterId,
  ...props
}: RemoteFileBrowserProps) {
  return <RemoteFileBrowserSession key={clusterId} clusterId={clusterId} {...props} />;
}

function RemoteFileBrowserSession({
  clusterId,
  compact = false,
  onInsertPath,
  onUseAsScript,
}: RemoteFileBrowserProps) {
  const [requestedPath, setRequestedPath] = useState<string | null>(null);
  const [address, setAddress] = useState("");
  const [showHidden, setShowHidden] = useState(false);
  const [directory, setDirectory] = useState<RemoteDirectory | null>(null);
  const [directoryError, setDirectoryError] = useState<Error | null>(null);
  const [directoryLoading, setDirectoryLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);
  const [history, setHistory] = useState<string[]>([]);
  const [selected, setSelected] = useState<RemoteFileEntry | null>(null);
  const [preview, setPreview] = useState<RemoteFilePreview | null>(null);
  const [previewError, setPreviewError] = useState<Error | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [wrapLines, setWrapLines] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    void api
      .listRemoteDirectory(
        clusterId,
        { path: requestedPath, show_hidden: showHidden },
        controller.signal,
      )
      .then((result) => {
        setDirectory(result);
        setAddress(result.path);
      })
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setDirectoryError(asError(error));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setDirectoryLoading(false);
      });
    return () => controller.abort();
  }, [clusterId, requestedPath, refreshKey, showHidden]);

  useEffect(() => {
    if (!selected || selected.kind === "directory" || selected.target_kind === "directory") {
      return;
    }
    const controller = new AbortController();
    void api
      .previewRemoteFile(clusterId, { path: selected.path }, controller.signal)
      .then(setPreview)
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setPreviewError(asError(error));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setPreviewLoading(false);
      });
    return () => controller.abort();
  }, [clusterId, selected]);

  function navigate(path: string, addHistory = true) {
    if (addHistory && directory?.path && path !== directory.path) {
      setHistory((current) => [...current.slice(-29), directory.path]);
    }
    beginDirectoryLoad();
    setRequestedPath(path);
  }

  function beginDirectoryLoad() {
    setDirectoryLoading(true);
    setDirectoryError(null);
    setDirectory(null);
    setSelected(null);
    setPreview(null);
    setPreviewError(null);
  }

  function submitAddress() {
    if (address.startsWith("/")) navigate(address);
  }

  function openEntry(entry: RemoteFileEntry) {
    if (entry.kind === "directory" || entry.target_kind === "directory") {
      navigate(entry.path);
      return;
    }
    setPreviewLoading(true);
    setPreview(null);
    setPreviewError(null);
    setSelected(entry);
  }

  const crumbs = directory ? breadcrumbs(directory.path) : [];
  const canUseAsScript =
    preview?.status === "available" &&
    preview.content != null &&
    (preview.language === "shell" || preview.content.startsWith("#!"));
  const extensions = [
    ...(preview?.language ? languageExtension(preview.language) : []),
    ...(wrapLines ? [EditorView.lineWrapping] : []),
  ];

  return (
    <section className={`remote-files${compact ? " remote-files--compact" : ""}`} aria-label="Read-only remote files">
      <header className="remote-files__toolbar">
        <div className="remote-files__navigation">
          <button
            className="icon-button"
            type="button"
            title="Back"
            aria-label="Back"
            disabled={history.length === 0}
            onClick={() => {
              const previous = history.at(-1);
              if (!previous) return;
              setHistory((current) => current.slice(0, -1));
              navigate(previous, false);
            }}
          >
            ←
          </button>
          <button
            className="icon-button"
            type="button"
            title="Up"
            aria-label="Up one directory"
            disabled={!directory?.parent_path}
            onClick={() => directory?.parent_path && navigate(directory.parent_path)}
          >
            ↑
          </button>
          <button
            className="icon-button"
            type="button"
            title="Refresh"
            aria-label="Refresh directory"
            onClick={() => {
              beginDirectoryLoad();
              setRefreshKey((value) => value + 1);
            }}
          >
            ↻
          </button>
        </div>
        <div className="remote-files__address">
          <label className="sr-only" htmlFor={`remote-path-${compact ? "compact" : "page"}`}>
            Absolute remote path
          </label>
          <input
            id={`remote-path-${compact ? "compact" : "page"}`}
            value={address}
            placeholder="Remote login directory"
            spellCheck={false}
            onChange={(event) => setAddress(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                submitAddress();
              }
            }}
          />
          <button className="button button--secondary" type="button" disabled={!address.startsWith("/")} onClick={submitAddress}>
            Go
          </button>
        </div>
        <label className="remote-files__hidden-toggle">
          <input
            type="checkbox"
            checked={showHidden}
            onChange={(event) => {
              beginDirectoryLoad();
              setShowHidden(event.target.checked);
            }}
          />
          Hidden files
        </label>
      </header>

      {crumbs.length > 0 ? (
        <nav className="remote-files__breadcrumbs" aria-label="Remote path">
          {crumbs.map((crumb) => (
            <button type="button" key={crumb.path} onClick={() => navigate(crumb.path)}>
              {crumb.label}
            </button>
          ))}
        </nav>
      ) : null}

      {directoryError ? (
        <div className="inline-state inline-state--error" role="alert">
          <strong>Cannot open this directory.</strong>
          <span>{directoryError.message}</span>
        </div>
      ) : null}
      {directory?.truncated ? (
        <p className="remote-files__notice" role="status">
          Showing the first 500 entries. Refine the path to browse the rest.
        </p>
      ) : null}

      <div className="remote-files__workspace">
        <div className="remote-files__listing" aria-busy={directoryLoading}>
          {directoryLoading && !directory ? <p className="remote-files__loading">Loading directory…</p> : null}
          {directory ? (
            <table>
              <thead>
                <tr><th>Name</th><th>Type</th><th>Size</th><th>Modified</th><th>Permissions</th></tr>
              </thead>
              <tbody>
                {directory.entries.map((entry) => (
                  <tr key={entry.path} className={selected?.path === entry.path ? "is-selected" : undefined}>
                    <td>
                      <button type="button" onClick={() => openEntry(entry)}>
                        <span aria-hidden="true">{entryIcon(entry)}</span>
                        <span>{entry.name}</span>
                        {entry.kind === "symlink" ? <small> → {entry.symlink_target}</small> : null}
                      </button>
                    </td>
                    <td>{entry.kind === "symlink" ? `symlink → ${entry.target_kind ?? "missing"}` : entry.kind}</td>
                    <td>{entry.kind === "directory" ? "—" : formatBytes(entry.size_bytes)}</td>
                    <td>{formatDateTime(entry.modified_at)}</td>
                    <td><code>{entry.permissions}</code></td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </div>

        <aside className="remote-files__preview" aria-live="polite">
          {!selected ? (
            <div className="remote-files__preview-empty">
              <span aria-hidden="true">⌘</span>
              <strong>Select a file to inspect it</strong>
              <p>Remote content stays read-only.</p>
            </div>
          ) : previewLoading ? (
            <p className="remote-files__loading">Inspecting {selected.name}…</p>
          ) : previewError ? (
            <div className="inline-state inline-state--error" role="alert">
              <strong>Preview unavailable.</strong><span>{previewError.message}</span>
            </div>
          ) : preview ? (
            <>
              <header className="remote-preview__header">
                <div>
                  <strong>{preview.name}</strong>
                  <span>
                    {formatBytes(preview.size_bytes)} · {preview.permissions}
                    {preview.symlink_target ? ` · symlink → ${preview.symlink_target}` : ""}
                  </span>
                </div>
                <div className="remote-preview__actions">
                  {onInsertPath ? (
                    <button className="button button--secondary" type="button" onClick={() => onInsertPath(quotePosixPath(preview.path), preview.path)}>
                      Insert path
                    </button>
                  ) : null}
                  {onUseAsScript && canUseAsScript ? (
                    <button className="button button--primary" type="button" onClick={() => onUseAsScript(preview.content ?? "", preview.path)}>
                      Use as job script
                    </button>
                  ) : null}
                  <label className="remote-preview__wrap">
                    <input type="checkbox" checked={wrapLines} onChange={(event) => setWrapLines(event.target.checked)} /> Wrap
                  </label>
                </div>
              </header>
              {preview.status === "available" && preview.content != null ? (
                <CodeMirror
                  className="remote-preview__editor"
                  value={preview.content}
                  height={compact ? "320px" : "520px"}
                  extensions={extensions}
                  readOnly
                  editable={false}
                  basicSetup={{
                    lineNumbers: true,
                    foldGutter: true,
                    highlightActiveLine: false,
                    highlightActiveLineGutter: false,
                    searchKeymap: true,
                  }}
                />
              ) : (
                <PreviewUnavailable status={preview.status} />
              )}
            </>
          ) : null}
        </aside>
      </div>
    </section>
  );
}

function PreviewUnavailable({ status }: { status: RemoteFilePreview["status"] }) {
  const message = {
    binary: "This file is binary or is not valid UTF-8. Metadata is available, but content is not loaded.",
    too_large: "This file is larger than the 1 MiB preview limit. Metadata is available, but content is not loaded.",
    special: "This is not an ordinary file. Devices, sockets, FIFOs, and directories are never read.",
    available: "No preview content is available.",
  }[status];
  return <div className="remote-files__preview-empty"><strong>Metadata only</strong><p>{message}</p></div>;
}

function languageExtension(language: string): Array<LanguageSupport | ReturnType<typeof StreamLanguage.define>> {
  switch (language) {
    case "shell": return [StreamLanguage.define(shell)];
    case "python": return [python()];
    case "json": return [json()];
    case "yaml": return [yaml()];
    case "javascript":
    case "typescript": return [javascript({ typescript: language === "typescript", jsx: true })];
    case "markdown": return [markdown()];
    case "css": return [css()];
    case "html": return [html()];
    case "c":
    case "cpp": return [cpp()];
    default: return [];
  }
}

function breadcrumbs(path: string) {
  if (path === "/") return [{ label: "/", path: "/" }];
  const parts = path.split("/").filter(Boolean);
  return [
    { label: "/", path: "/" },
    ...parts.map((part, index) => ({
      label: part,
      path: `/${parts.slice(0, index + 1).join("/")}`,
    })),
  ];
}

function entryIcon(entry: RemoteFileEntry) {
  if (entry.kind === "directory" || entry.target_kind === "directory") return "▰";
  if (entry.kind === "symlink") return "↗";
  if (entry.kind === "other") return "◇";
  return "▤";
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MiB`;
}

function asError(value: unknown): Error {
  return value instanceof Error ? value : new Error("The remote file request failed.");
}
