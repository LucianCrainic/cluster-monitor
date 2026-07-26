export function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "Not yet";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(date);
}

export function formatRelativeTime(
  value: string | null | undefined,
  now = Date.now(),
): string {
  if (!value) {
    return "Awaiting first refresh";
  }

  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) {
    return value;
  }

  const seconds = Math.round((timestamp - now) / 1000);
  const absoluteSeconds = Math.abs(seconds);
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

  if (absoluteSeconds < 60) {
    return formatter.format(seconds, "second");
  }

  const minutes = Math.round(seconds / 60);
  if (Math.abs(minutes) < 60) {
    return formatter.format(minutes, "minute");
  }

  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 24) {
    return formatter.format(hours, "hour");
  }

  return formatter.format(Math.round(hours / 24), "day");
}

export function displayValue(
  value: string | number | null | undefined,
  fallback = "—",
): string {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }
  return String(value);
}

export function titleCase(value: string): string {
  return value
    .toLowerCase()
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

export function formatDuration(
  totalSeconds: number | null | undefined,
): string {
  if (totalSeconds === null || totalSeconds === undefined) {
    return "—";
  }

  if (!Number.isFinite(totalSeconds) || totalSeconds < 0) {
    return "—";
  }

  const seconds = Math.floor(totalSeconds);
  const days = Math.floor(seconds / 86_400);
  const hours = Math.floor((seconds % 86_400) / 3_600);
  const minutes = Math.floor((seconds % 3_600) / 60);
  const remainingSeconds = seconds % 60;
  const time = [hours, minutes, remainingSeconds]
    .map((part) => String(part).padStart(2, "0"))
    .join(":");

  return days > 0 ? `${days}d ${time}` : time;
}

export function formatMemory(megabytes: number | null | undefined): string {
  if (megabytes === null || megabytes === undefined) {
    return "—";
  }
  if (megabytes >= 1024) {
    const gibibytes = megabytes / 1024;
    return `${gibibytes.toLocaleString(undefined, {
      maximumFractionDigits: gibibytes < 10 ? 1 : 0,
    })} GiB`;
  }
  return `${megabytes.toLocaleString()} MiB`;
}
