import {
  Fragment,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from "react";

import { ApiError, streamJobLogs } from "../api/client";
import type { JobLogEvent, JobLogSource } from "../types/api";

const MAX_BUFFER_LINES = 5_000;
const MAX_BUFFER_CHARS = 2 * 1024 * 1024;

type ViewerStatus =
  | "connecting"
  | "waiting"
  | "live"
  | "finalizing"
  | "completed"
  | "unavailable"
  | "disconnected";

interface LogLine {
  id: string;
  source: JobLogSource;
  text: string;
}

interface ViewerState {
  lines: LogLine[];
  openLines: Partial<Record<JobLogSource, string>>;
  sources: JobLogSource[];
  status: ViewerStatus;
  message: string;
  trimmed: boolean;
}

type ViewerAction =
  | { type: "reset" }
  | { type: "event"; event: JobLogEvent }
  | { type: "disconnected"; message: string };

const initialState: ViewerState = {
  lines: [],
  openLines: {},
  sources: [],
  status: "connecting",
  message: "Connecting to the job output…",
  trimmed: false,
};

export function JobLogViewer({
  clusterId,
  jobId,
}: {
  clusterId: string;
  jobId: string;
}) {
  const [state, dispatch] = useReducer(viewerReducer, initialState);
  const [connectionAttempt, setConnectionAttempt] = useState(0);
  const [selectedSource, setSelectedSource] = useState<"all" | JobLogSource>("all");
  const [query, setQuery] = useState("");
  const [currentMatch, setCurrentMatch] = useState(-1);
  const [wrap, setWrap] = useState(false);
  const [autoscroll, setAutoscroll] = useState(true);
  const [actionMessage, setActionMessage] = useState("");
  const surfaceRef = useRef<HTMLDivElement>(null);
  const lineRefs = useRef(new Map<string, HTMLDivElement>());

  useEffect(() => {
    const controller = new AbortController();
    let completed = false;
    dispatch({ type: "reset" });

    async function consume() {
      try {
        for await (const event of streamJobLogs(clusterId, jobId, controller.signal)) {
          if (event.type === "complete") {
            completed = true;
          }
          dispatch({ type: "event", event });
        }
        if (!completed && !controller.signal.aborted) {
          dispatch({
            type: "disconnected",
            message: "The live log connection closed. Reconnect to continue.",
          });
        }
      } catch (error) {
        if (controller.signal.aborted) {
          return;
        }
        dispatch({
          type: "disconnected",
          message:
            error instanceof ApiError
              ? error.message
              : "The live log connection failed. Reconnect to try again.",
        });
      }
    }

    void consume();
    return () => controller.abort();
  }, [clusterId, connectionAttempt, jobId]);

  const source: "all" | JobLogSource =
    state.sources.length === 1 && state.sources[0] === "combined"
      ? "combined"
      : selectedSource !== "all" && state.sources.includes(selectedSource)
        ? selectedSource
        : "all";

  const filteredLines = useMemo(
    () =>
      source === "all"
        ? state.lines
        : state.lines.filter((line) => line.source === source),
    [source, state.lines],
  );
  const normalizedQuery = query.toLocaleLowerCase();
  const matchingLines = useMemo(
    () =>
      normalizedQuery
        ? filteredLines.filter((line) =>
            line.text.toLocaleLowerCase().includes(normalizedQuery),
          )
        : [],
    [filteredLines, normalizedQuery],
  );

  const visibleMatch =
    matchingLines.length === 0 ? -1 : Math.min(currentMatch, matchingLines.length - 1);

  useEffect(() => {
    if (!autoscroll) {
      return;
    }
    const surface = surfaceRef.current;
    if (surface) {
      surface.scrollTop = surface.scrollHeight;
    }
  }, [autoscroll, state.lines]);

  const snapshot = useMemo(
    () =>
      filteredLines
        .map((line) =>
          source === "all" && state.sources.length > 1
            ? `[${line.source}] ${line.text}`
            : line.text,
        )
        .join("\n"),
    [filteredLines, source, state.sources.length],
  );

  function moveToMatch(direction: 1 | -1) {
    if (matchingLines.length === 0) {
      return;
    }
    const next =
      (visibleMatch + direction + matchingLines.length) % matchingLines.length;
    setCurrentMatch(next);
    setAutoscroll(false);
    const matchingLine = matchingLines[next];
    if (matchingLine) {
      lineRefs.current.get(matchingLine.id)?.scrollIntoView({ block: "center" });
    }
  }

  async function copySnapshot() {
    try {
      await navigator.clipboard.writeText(snapshot);
      setActionMessage("Copied the buffered log output.");
    } catch {
      setActionMessage("The browser could not copy the log output.");
    }
  }

  function downloadSnapshot() {
    const blob = new Blob([snapshot], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const safeSource = source === "all" ? "all" : source;
    link.href = url;
    link.download = `${sanitizeFilename(clusterId)}-${sanitizeFilename(jobId)}-${safeSource}-logs.txt`;
    link.click();
    URL.revokeObjectURL(url);
    setActionMessage("Downloaded the buffered log snapshot.");
  }

  const currentMatchId = matchingLines[visibleMatch]?.id;
  const showSourceLabels = source === "all" && state.sources.length > 1;

  return (
    <section className="job-logs" aria-labelledby="job-logs-heading">
      <div className="job-logs__header">
        <div>
          <p className="section-eyebrow">Remote output</p>
          <h2 id="job-logs-heading">Live job logs</h2>
          <p className="job-logs__status-message" aria-live="polite">
            {state.message}
          </p>
        </div>
        <div className={`log-status log-status--${state.status}`}>
          <span aria-hidden="true" />
          {statusLabel(state.status)}
        </div>
      </div>

      <div className="job-logs__toolbar">
        <div className="log-source-filter" role="group" aria-label="Log source">
          {state.sources.length > 1 ? (
            <button
              className={source === "all" ? "is-active" : undefined}
              type="button"
              onClick={() => {
                setSelectedSource("all");
                setCurrentMatch(0);
              }}
            >
              All
            </button>
          ) : null}
          {state.sources.map((candidate) => (
            <button
              className={source === candidate ? "is-active" : undefined}
              key={candidate}
              type="button"
              onClick={() => {
                setSelectedSource(candidate);
                setCurrentMatch(0);
              }}
            >
              {sourceLabel(candidate)}
            </button>
          ))}
        </div>

        <label className="log-search">
          <span>Search logs</span>
          <input
            type="search"
            value={query}
            placeholder="Find text…"
            onChange={(event) => {
              setQuery(event.target.value);
              setCurrentMatch(0);
            }}
          />
        </label>
        <div className="log-search-nav" aria-live="polite">
          <span>
            {normalizedQuery
              ? `${matchingLines.length === 0 ? 0 : visibleMatch + 1} of ${matchingLines.length}`
              : "No search"}
          </span>
          <button
            type="button"
            aria-label="Previous log match"
            disabled={matchingLines.length === 0}
            onClick={() => moveToMatch(-1)}
          >
            ↑
          </button>
          <button
            type="button"
            aria-label="Next log match"
            disabled={matchingLines.length === 0}
            onClick={() => moveToMatch(1)}
          >
            ↓
          </button>
        </div>

        <button
          className="button button--secondary button--compact"
          type="button"
          onClick={() => setWrap((value) => !value)}
        >
          {wrap ? "No wrap" : "Wrap lines"}
        </button>
        <button
          className="button button--secondary button--compact"
          type="button"
          disabled={!snapshot}
          onClick={() => void copySnapshot()}
        >
          Copy
        </button>
        <button
          className="button button--secondary button--compact"
          type="button"
          disabled={!snapshot}
          onClick={downloadSnapshot}
        >
          Download
        </button>
        <button
          className="button button--secondary button--compact"
          type="button"
          onClick={() => {
            setAutoscroll(true);
            setActionMessage("");
            setConnectionAttempt((value) => value + 1);
          }}
        >
          Reconnect
        </button>
      </div>

      {state.trimmed ? (
        <p className="job-logs__notice" role="status">
          Earlier output was trimmed to keep the viewer responsive.
        </p>
      ) : null}

      <div
        className={`log-terminal${wrap ? " log-terminal--wrap" : ""}`}
        ref={surfaceRef}
        role="log"
        aria-live="off"
        aria-label={`Log output for job ${jobId}`}
        onScroll={(event) => {
          const element = event.currentTarget;
          const atBottom =
            element.scrollHeight - element.scrollTop - element.clientHeight < 24;
          setAutoscroll(atBottom);
        }}
      >
        {filteredLines.length === 0 ? (
          <div className="log-terminal__empty">{emptyMessage(state.status)}</div>
        ) : (
          filteredLines.map((line) => (
            <div
              className={`log-line${line.id === currentMatchId ? " log-line--current" : ""}`}
              key={line.id}
              ref={(element) => {
                if (element) {
                  lineRefs.current.set(line.id, element);
                } else {
                  lineRefs.current.delete(line.id);
                }
              }}
            >
              {showSourceLabels ? (
                <span className={`log-line__source log-line__source--${line.source}`}>
                  {sourceLabel(line.source)}
                </span>
              ) : null}
              <span className="log-line__text">
                <HighlightedText text={line.text} query={query} />
              </span>
            </div>
          ))
        )}
      </div>

      <div className="job-logs__footer">
        <label>
          <input
            type="checkbox"
            checked={autoscroll}
            onChange={(event) => setAutoscroll(event.target.checked)}
          />
          Follow latest output
        </label>
        {!autoscroll ? (
          <button
            className="button button--secondary button--compact"
            type="button"
            onClick={() => setAutoscroll(true)}
          >
            Jump to latest
          </button>
        ) : null}
        <span>{filteredLines.length.toLocaleString()} buffered lines</span>
        {actionMessage ? <span aria-live="polite">{actionMessage}</span> : null}
      </div>
    </section>
  );
}

function viewerReducer(state: ViewerState, action: ViewerAction): ViewerState {
  if (action.type === "reset") {
    return initialState;
  }
  if (action.type === "disconnected") {
    return { ...state, status: "disconnected", message: action.message };
  }
  const event = action.event;
  if (event.type === "metadata") {
    return {
      ...state,
      sources: event.sources,
      message: `Showing the latest ${event.initial_lines} lines per logfile.`,
    };
  }
  if (event.type === "status") {
    return { ...state, status: event.status, message: event.message };
  }
  if (event.type === "error") {
    return {
      ...state,
      status: event.retryable ? "disconnected" : "unavailable",
      message: event.message,
    };
  }
  if (event.type === "complete") {
    return {
      ...state,
      status: event.reason === "unavailable" ? "unavailable" : "completed",
      message:
        event.reason === "unavailable"
          ? state.message
          : "The job log stream is complete.",
    };
  }
  return appendChunk(state, event);
}

function appendChunk(
  state: ViewerState,
  event: Extract<JobLogEvent, { type: "chunk" }>,
): ViewerState {
  const lines = state.lines.map((line) => ({ ...line }));
  const openLines = { ...state.openLines };
  const parts = event.text.split("\n");
  for (let index = 0; index < parts.length; index += 1) {
    const part = parts[index];
    const endsLine = index < parts.length - 1;
    const openId = openLines[event.source];
    let line = openId ? lines.find((candidate) => candidate.id === openId) : undefined;
    if (!line && (part || endsLine)) {
      line = {
        id: `${event.sequence}-${event.source}-${index}`,
        source: event.source,
        text: "",
      };
      lines.push(line);
      openLines[event.source] = line.id;
    }
    if (line) {
      line.text += part;
    }
    if (endsLine) {
      delete openLines[event.source];
    }
  }

  let characters = lines.reduce((total, line) => total + line.text.length, 0);
  let trimmed = state.trimmed;
  while (lines.length > MAX_BUFFER_LINES || characters > MAX_BUFFER_CHARS) {
    if (lines.length === 1) {
      const excess = characters - MAX_BUFFER_CHARS;
      const onlyLine = lines[0];
      if (onlyLine) {
        onlyLine.text = onlyLine.text.slice(Math.max(0, excess));
      }
      trimmed = true;
      break;
    }
    const removed = lines.shift();
    if (!removed) {
      break;
    }
    characters -= removed.text.length;
    if (openLines[removed.source] === removed.id) {
      delete openLines[removed.source];
    }
    trimmed = true;
  }
  return { ...state, lines, openLines, trimmed };
}

function HighlightedText({ text, query }: { text: string; query: string }) {
  if (!query) {
    return text;
  }
  const normalizedText = text.toLocaleLowerCase();
  const normalizedQuery = query.toLocaleLowerCase();
  const parts: Array<{ text: string; match: boolean }> = [];
  let offset = 0;
  let match = normalizedText.indexOf(normalizedQuery);
  while (match >= 0) {
    parts.push({ text: text.slice(offset, match), match: false });
    parts.push({ text: text.slice(match, match + query.length), match: true });
    offset = match + query.length;
    match = normalizedText.indexOf(normalizedQuery, offset);
  }
  parts.push({ text: text.slice(offset), match: false });
  return parts.map((part, index) =>
    part.match ? <mark key={index}>{part.text}</mark> : <Fragment key={index}>{part.text}</Fragment>,
  );
}

function statusLabel(status: ViewerStatus): string {
  return {
    connecting: "Connecting",
    waiting: "Waiting",
    live: "Live",
    finalizing: "Finalizing",
    completed: "Completed",
    unavailable: "Unavailable",
    disconnected: "Disconnected",
  }[status];
}

function sourceLabel(source: JobLogSource): string {
  return { stdout: "stdout", stderr: "stderr", combined: "combined" }[source];
}

function emptyMessage(status: ViewerStatus): string {
  if (status === "waiting") {
    return "The job is waiting to start. Output will appear when Slurm creates the file.";
  }
  if (status === "unavailable") {
    return "No readable output is available for this job.";
  }
  if (status === "disconnected") {
    return "The stream is disconnected. Use Reconnect to try again.";
  }
  return "Waiting for log output…";
}

function sanitizeFilename(value: string): string {
  return value.replace(/[^A-Za-z0-9_.-]+/g, "-");
}
