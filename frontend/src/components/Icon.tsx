import type { ReactNode, SVGProps } from "react";

export type IconName =
  | "overview"
  | "jobs"
  | "history"
  | "topology"
  | "files"
  | "collapse"
  | "expand"
  | "cpu"
  | "memory"
  | "gpu"
  | "nodes"
  | "clock"
  | "terminal"
  | "search"
  | "grid"
  | "list"
  | "play"
  | "pause"
  | "maximize"
  | "minimize"
  | "file"
  | "link"
  | "arrowLeft"
  | "arrowUp"
  | "refresh"
  | "copy"
  | "trash";

const paths: Record<IconName, ReactNode> = {
  overview: <><rect x="3" y="3" width="7" height="7" rx="2" /><rect x="14" y="3" width="7" height="7" rx="2" /><rect x="3" y="14" width="7" height="7" rx="2" /><rect x="14" y="14" width="7" height="7" rx="2" /></>,
  jobs: <><path d="M9 6h11M9 12h11M9 18h11" /><path d="m4 6 .7.7L6 5.2M4 12l.7.7L6 11.2M4 18l.7.7L6 17.2" /></>,
  history: <><path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5M12 7v5l3 2" /></>,
  topology: <><rect x="9" y="3" width="6" height="5" rx="1.5" /><rect x="3" y="16" width="6" height="5" rx="1.5" /><rect x="15" y="16" width="6" height="5" rx="1.5" /><path d="M12 8v4M6 16v-4h12v4" /></>,
  files: <><path d="M3 7.5h7l2-3h9v15H3z" /><path d="M3 9h18" /></>,
  collapse: <path d="M15 18 9 12l6-6" />,
  expand: <path d="m9 18 6-6-6-6" />,
  cpu: <><rect x="6" y="6" width="12" height="12" rx="2" /><path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3M10 10h4v4h-4z" /></>,
  memory: <><path d="M4 6h16v12H4zM8 9v6M12 9v6M16 9v6M7 3v3M12 3v3M17 3v3M7 18v3M12 18v3M17 18v3" /></>,
  gpu: <><rect x="3" y="5" width="18" height="14" rx="2" /><circle cx="10" cy="12" r="4" /><path d="M14 9h4M14 12h4M14 15h4M7 2v3M17 2v3" /></>,
  nodes: <><circle cx="5" cy="12" r="2.5" /><circle cx="19" cy="6" r="2.5" /><circle cx="19" cy="18" r="2.5" /><path d="m7.5 11 9-4M7.5 13l9 4" /></>,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  terminal: <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="m7 9 3 3-3 3M13 15h4" /></>,
  search: <><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" /></>,
  grid: <><rect x="4" y="4" width="6" height="6" rx="1" /><rect x="14" y="4" width="6" height="6" rx="1" /><rect x="4" y="14" width="6" height="6" rx="1" /><rect x="14" y="14" width="6" height="6" rx="1" /></>,
  list: <><path d="M9 6h11M9 12h11M9 18h11" /><circle cx="4.5" cy="6" r=".7" fill="currentColor" stroke="none" /><circle cx="4.5" cy="12" r=".7" fill="currentColor" stroke="none" /><circle cx="4.5" cy="18" r=".7" fill="currentColor" stroke="none" /></>,
  play: <path d="m9 7 8 5-8 5z" />,
  pause: <><path d="M9 7v10M15 7v10" /></>,
  maximize: <><path d="M8 3H3v5M16 3h5v5M21 16v5h-5M3 16v5h5" /></>,
  minimize: <><path d="M8 3v5H3M16 3v5h5M21 16h-5v5M3 16h5v5" /></>,
  file: <><path d="M6 2h8l4 4v16H6z" /><path d="M14 2v5h5M9 12h6M9 16h6" /></>,
  link: <><path d="M10 13a5 5 0 0 0 7.1.1l2-2a5 5 0 0 0-7.1-7.1l-1.1 1.1" /><path d="M14 11a5 5 0 0 0-7.1-.1l-2 2A5 5 0 0 0 12 20l1.1-1.1" /></>,
  arrowLeft: <><path d="m10 6-6 6 6 6" /><path d="M4 12h16" /></>,
  arrowUp: <><path d="m6 10 6-6 6 6" /><path d="M12 4v16" /></>,
  refresh: <><path d="M20 7v5h-5" /><path d="M4 17v-5h5" /><path d="M18.5 9a7 7 0 0 0-12-2L4 9M5.5 15a7 7 0 0 0 12 2l2.5-2" /></>,
  copy: <><rect x="8" y="8" width="12" height="12" rx="2" /><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" /></>,
  trash: <><path d="M4 7h16M9 3h6l1 4H8zM7 7l1 14h8l1-14M10 11v6M14 11v6" /></>,
};

export function Icon({ name, ...props }: { name: IconName } & SVGProps<SVGSVGElement>) {
  return (
    <svg
      aria-hidden="true"
      fill="none"
      height="20"
      viewBox="0 0 24 24"
      width="20"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.7"
      {...props}
    >
      {paths[name]}
    </svg>
  );
}
