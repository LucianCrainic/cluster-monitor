interface RefreshButtonProps {
  isRefreshing: boolean;
  onRefresh: () => void;
}

export function RefreshButton({
  isRefreshing,
  onRefresh,
}: RefreshButtonProps) {
  return (
    <button
      className="button button--secondary refresh-button"
      type="button"
      onClick={onRefresh}
      disabled={isRefreshing}
    >
      <span
        className={`refresh-button__icon${isRefreshing ? " is-spinning" : ""}`}
        aria-hidden="true"
      >
        ↻
      </span>
      {isRefreshing ? "Refreshing…" : "Refresh"}
    </button>
  );
}
