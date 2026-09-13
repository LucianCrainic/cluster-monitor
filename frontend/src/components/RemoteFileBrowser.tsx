import { cpp } from "@codemirror/lang-cpp";
import { css } from "@codemirror/lang-css";
import { html } from "@codemirror/lang-html";
import { javascript } from "@codemirror/lang-javascript";
import { json } from "@codemirror/lang-json";
import { markdown } from "@codemirror/lang-markdown";
import { python } from "@codemirror/lang-python";
import { yaml } from "@codemirror/lang-yaml";
import {
  HighlightStyle,
  StreamLanguage,
  syntaxHighlighting,
  type LanguageSupport,
} from "@codemirror/language";
import { diff } from "@codemirror/legacy-modes/mode/diff";
import { dockerFile } from "@codemirror/legacy-modes/mode/dockerfile";
import { properties } from "@codemirror/legacy-modes/mode/properties";
import { shell } from "@codemirror/legacy-modes/mode/shell";
import { standardSQL } from "@codemirror/legacy-modes/mode/sql";
import { toml } from "@codemirror/legacy-modes/mode/toml";
import { xml } from "@codemirror/legacy-modes/mode/xml";
import { EditorView } from "@codemirror/view";
import { tags } from "@lezer/highlight";
import CodeMirror from "@uiw/react-codemirror";
import { useEffect, useMemo, useState } from "react";

import { api } from "../api/client";
import type {
  RemoteDirectory,
  RemoteFileEntry,
  RemoteFilePreview,
} from "../types/api";
import { formatDateTime } from "../utils/format";
import { quotePosixPath } from "../utils/paths";
import { Icon } from "./Icon";

const fileEditorTheme = EditorView.theme({
  "&": {
    height: "100%",
    color: "var(--editor-foreground)",
    backgroundColor: "var(--editor-background)",
    fontSize: "12px",
  },
  "&.cm-focused": { outline: "none" },
  ".cm-scroller": {
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
    lineHeight: "1.65",
  },
  ".cm-content": { padding: "13px 0", caretColor: "var(--green)" },
  ".cm-line": { padding: "0 16px" },
  ".cm-gutters": {
    color: "var(--editor-gutter-foreground)",
    backgroundColor: "var(--editor-gutter-background)",
    borderRight: "1px solid var(--editor-border)",
  },
  ".cm-lineNumbers .cm-gutterElement": { minWidth: "42px", padding: "0 11px 0 8px" },
  ".cm-foldGutter .cm-gutterElement": { padding: "0 7px" },
  ".cm-cursor, .cm-dropCursor": { borderLeftColor: "var(--green)" },
  "&.cm-focused .cm-selectionBackground, .cm-selectionBackground": {
    backgroundColor: "var(--editor-selection) !important",
  },
  ".cm-matchingBracket": {
    color: "inherit",
    backgroundColor: "var(--editor-bracket-match)",
    outline: "1px solid var(--green)",
  },
});

const fileHighlightStyle = HighlightStyle.define([
  { tag: tags.keyword, color: "var(--syntax-keyword)", fontWeight: "650" },
  { tag: [tags.typeName, tags.className, tags.namespace], color: "var(--syntax-type)" },
  {
    tag: [tags.function(tags.variableName), tags.definition(tags.variableName)],
    color: "var(--syntax-function)",
  },
  { tag: [tags.string, tags.special(tags.string)], color: "var(--syntax-string)" },
  { tag: [tags.number, tags.bool, tags.null], color: "var(--syntax-number)" },
  { tag: [tags.propertyName, tags.attributeName], color: "var(--syntax-property)" },
  { tag: [tags.operator, tags.operatorKeyword], color: "var(--syntax-operator)" },
  { tag: [tags.comment, tags.docComment], color: "var(--syntax-comment)", fontStyle: "italic" },
  { tag: [tags.meta, tags.processingInstruction], color: "var(--syntax-meta)" },
  { tag: [tags.heading, tags.strong], color: "var(--syntax-heading)", fontWeight: "700" },
  { tag: [tags.link, tags.url], color: "var(--syntax-link)", textDecoration: "underline" },
  { tag: tags.invalid, color: "var(--syntax-invalid)", textDecoration: "underline wavy" },
]);

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
  const [filter, setFilter] = useState("");
  const [actionMessage, setActionMessage] = useState("");

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
    setFilter("");
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
    setActionMessage("");
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
  const normalizedFilter = filter.trim().toLocaleLowerCase();
  const visibleEntries = useMemo(
    () =>
      directory?.entries.filter((entry) =>
        normalizedFilter ? entry.name.toLocaleLowerCase().includes(normalizedFilter) : true,
      ) ?? [],
    [directory, normalizedFilter],
  );
  const canUseAsScript =
    preview?.status === "available" &&
    preview.content != null &&
    (preview.language === "shell" || preview.content.startsWith("#!"));
  const extensions = [
    fileEditorTheme,
    syntaxHighlighting(fileHighlightStyle),
    ...(preview?.language ? languageExtension(preview.language) : []),
    ...(wrapLines ? [EditorView.lineWrapping] : []),
  ];
  const previewLineCount = countContentLines(preview?.content);

  async function copyPreviewPath() {
    if (!preview) return;
    try {
      await navigator.clipboard.writeText(preview.path);
      setActionMessage("Copied the remote path.");
    } catch {
      setActionMessage("The browser could not copy the remote path.");
    }
  }

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
            <Icon name="arrowLeft" />
          </button>
          <button
            className="icon-button"
            type="button"
            title="Up"
            aria-label="Up one directory"
            disabled={!directory?.parent_path}
            onClick={() => directory?.parent_path && navigate(directory.parent_path)}
          >
            <Icon name="arrowUp" />
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
            <Icon name="refresh" />
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
          {crumbs.map((crumb, index) => (
            <button
              type="button"
              key={crumb.path}
              aria-current={index === crumbs.length - 1 ? "location" : undefined}
              onClick={() => navigate(crumb.path)}
            >
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
            <>
              <header className="remote-files__listing-header">
                <div>
                  <strong>Directory contents</strong>
                  <span>
                    {normalizedFilter
                      ? `${visibleEntries.length} of ${directory.entries.length} entries`
                      : `${directory.entries.length} ${directory.entries.length === 1 ? "entry" : "entries"}`}
                  </span>
                </div>
                <label className="remote-files__filter">
                  <span className="sr-only">Filter directory</span>
                  <Icon name="search" />
                  <input
                    type="search"
                    value={filter}
                    placeholder="Filter this directory…"
                    aria-label="Filter directory"
                    onChange={(event) => setFilter(event.target.value)}
                  />
                </label>
              </header>
              <div className="remote-files__table-wrap">
                <table>
                  <thead>
                    <tr><th>Name</th><th>Type</th><th>Size</th><th>Modified</th><th>Permissions</th></tr>
                  </thead>
                  <tbody>
                    {visibleEntries.map((entry) => (
                      <tr key={entry.path} className={selected?.path === entry.path ? "is-selected" : undefined}>
                        <td>
                          <button type="button" onClick={() => openEntry(entry)}>
                            <span className={`remote-file__icon remote-file__icon--${entry.kind}`} aria-hidden="true">
                              <Icon name={entryIcon(entry)} />
                            </span>
                            <span>{entry.name}</span>
                            {entry.kind === "symlink" ? <small> → {entry.symlink_target}</small> : null}
                          </button>
                        </td>
                        <td>{entryKindLabel(entry)}</td>
                        <td>{entry.kind === "directory" ? "—" : formatBytes(entry.size_bytes)}</td>
                        <td>{formatDateTime(entry.modified_at)}</td>
                        <td><code>{entry.permissions}</code></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {visibleEntries.length === 0 ? (
                  <div className="remote-files__no-results">
                    <Icon name="search" />
                    <strong>No matching files</strong>
                    <span>Try a shorter name or clear the directory filter.</span>
                  </div>
                ) : null}
              </div>
            </>
          ) : null}
        </div>

        <aside className="remote-files__preview" aria-label="File preview" aria-live="polite">
          {!selected ? (
            <div className="remote-files__preview-empty">
              <span aria-hidden="true"><Icon name="file" /></span>
              <strong>Select a file to inspect it</strong>
              <p>Preview source files with syntax highlighting while keeping the remote workspace read-only.</p>
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
                <div className="remote-preview__identity">
                  <span className="remote-preview__file-icon" aria-hidden="true">
                    <Icon name={selected.kind === "symlink" ? "link" : "file"} />
                  </span>
                  <div>
                    <span className="remote-preview__eyebrow">File preview</span>
                    <strong>{preview.name}</strong>
                    <code title={preview.path}>{preview.path}</code>
                  </div>
                </div>
                <div className="remote-preview__actions">
                  <button
                    className="button button--secondary"
                    type="button"
                    onClick={() => void copyPreviewPath()}
                  >
                    <Icon name="copy" />
                    Copy path
                  </button>
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
              <div className="remote-preview__metadata">
                <span className="remote-preview__language">{languageLabel(preview.language)}</span>
                <span>{formatBytes(preview.size_bytes)}</span>
                <code>{preview.permissions}</code>
                <span>Modified {formatDateTime(preview.modified_at)}</span>
                {preview.symlink_target ? <span>Symlink → {preview.symlink_target}</span> : null}
              </div>
              {actionMessage ? (
                <p className="remote-preview__action-message" aria-live="polite">
                  {actionMessage}
                </p>
              ) : null}
              {preview.status === "available" && preview.content != null ? (
                <div className="remote-preview__code">
                  <CodeMirror
                    className="remote-preview__editor"
                    value={preview.content}
                    height={compact ? "320px" : "540px"}
                    extensions={extensions}
                    readOnly
                    editable={false}
                    basicSetup={{
                      lineNumbers: true,
                      foldGutter: true,
                      bracketMatching: true,
                      highlightSelectionMatches: true,
                      highlightActiveLine: false,
                      highlightActiveLineGutter: false,
                      searchKeymap: true,
                    }}
                  />
                  <footer className="remote-preview__statusbar">
                    <span>{languageLabel(preview.language)} syntax</span>
                    <span>{previewLineCount.toLocaleString()} {previewLineCount === 1 ? "line" : "lines"}</span>
                    <span>UTF-8</span>
                    <span>Read only</span>
                  </footer>
                </div>
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
    case "toml": return [StreamLanguage.define(toml)];
    case "properties": return [StreamLanguage.define(properties)];
    case "dockerfile": return [StreamLanguage.define(dockerFile)];
    case "diff": return [StreamLanguage.define(diff)];
    case "sql": return [StreamLanguage.define(standardSQL)];
    case "xml": return [StreamLanguage.define(xml)];
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

function entryIcon(entry: RemoteFileEntry): "files" | "link" | "file" {
  if (entry.kind === "directory" || entry.target_kind === "directory") return "files";
  if (entry.kind === "symlink") return "link";
  return "file";
}

function entryKindLabel(entry: RemoteFileEntry) {
  if (entry.kind === "symlink") {
    return `Link to ${entry.target_kind ?? "missing target"}`;
  }
  return entry.kind === "directory" ? "Folder" : entry.kind === "file" ? "File" : "Other";
}

function languageLabel(language: string | null | undefined) {
  return {
    shell: "Shell",
    python: "Python",
    json: "JSON",
    yaml: "YAML",
    javascript: "JavaScript",
    typescript: "TypeScript",
    markdown: "Markdown",
    css: "CSS",
    html: "HTML",
    c: "C",
    cpp: "C++",
    toml: "TOML",
    properties: "Properties",
    dockerfile: "Dockerfile",
    diff: "Diff",
    sql: "SQL",
    xml: "XML",
    text: "Plain text",
  }[language ?? "text"] ?? "Plain text";
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MiB`;
}

function countContentLines(content: string | null | undefined) {
  if (!content) return 0;
  const lineBreaks = content.match(/\n/g)?.length ?? 0;
  return lineBreaks + (content.endsWith("\n") ? 0 : 1);
}

function asError(value: unknown): Error {
  return value instanceof Error ? value : new Error("The remote file request failed.");
}
