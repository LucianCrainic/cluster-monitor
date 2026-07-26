import { ApiError } from "../api/client";

interface LoadingStateProps {
  label?: string;
  variant?: "cards" | "table" | "detail";
}

export function LoadingState({
  label = "Loading cluster data…",
  variant = "cards",
}: LoadingStateProps) {
  const rows = variant === "table" ? 6 : variant === "detail" ? 4 : 3;
  return (
    <div className={`loading-state loading-state--${variant}`} role="status">
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }, (_, index) => (
        <div className="skeleton" key={index} aria-hidden="true">
          <span className="skeleton__line skeleton__line--short" />
          <span className="skeleton__line" />
        </div>
      ))}
    </div>
  );
}

interface ErrorStateProps {
  error: Error;
  onRetry: () => void;
  title?: string;
}

export function ErrorState({ error, onRetry, title }: ErrorStateProps) {
  const connectionError =
    error instanceof ApiError ? error.isConnectionError : false;
  const heading =
    title ?? (connectionError ? "Connection unavailable" : "Data unavailable");

  return (
    <section className="page-state page-state--error" role="alert">
      <span className="page-state__symbol" aria-hidden="true">
        !
      </span>
      <div>
        <h2>{heading}</h2>
        <p>{error.message}</p>
        <button className="button button--secondary" type="button" onClick={onRetry}>
          Try again
        </button>
      </div>
    </section>
  );
}

interface EmptyStateProps {
  title: string;
  description: string;
  action?: React.ReactNode;
}

export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <section className="page-state page-state--empty">
      <span className="page-state__symbol page-state__symbol--empty" aria-hidden="true">
        ···
      </span>
      <div>
        <h2>{title}</h2>
        <p>{description}</p>
        {action}
      </div>
    </section>
  );
}
