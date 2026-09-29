/** Geometric stroke icons only — no faces, no emoji. */
export type IconName =
  | "arrow-up"
  | "arrow-left"
  | "arrow-right"
  | "chevron-down"
  | "chevron-right"
  | "check"
  | "close"
  | "plus"
  | "trash"
  | "sun"
  | "moon"
  | "panel"
  | "desktop"
  | "tablet"
  | "mobile"
  | "refresh"
  | "external"
  | "code"
  | "eye"
  | "file"
  | "folder"
  | "contract"
  | "race"
  | "settings"
  | "gauge"
  | "logout"
  | "alert"
  | "sparkle"
  | "stop";

const PATHS: Record<IconName, string> = {
  "arrow-up": "M8 13V3m0 0L4 7m4-4 4 4",
  "arrow-left": "M13 8H3m0 0 4-4M3 8l4 4",
  "arrow-right": "M3 8h10m0 0-4-4m4 4-4 4",
  "chevron-down": "m4 6.5 4 4 4-4",
  "chevron-right": "m6.5 4 4 4-4 4",
  check: "m3.5 8.5 3 3 6-7",
  close: "m4 4 8 8M12 4l-8 8",
  plus: "M8 3.5v9M3.5 8h9",
  trash: "M3.5 5h9M6.5 5V3.5h3V5M5 5l.6 8h4.8L11 5",
  sun: "M8 10.8a2.8 2.8 0 1 0 0-5.6 2.8 2.8 0 0 0 0 5.6M8 1.6v1.4M8 13v1.4M1.6 8H3m10 0h1.4M3.5 3.5l1 1m7 7 1 1m0-9-1 1m-7 7-1 1",
  moon: "M13 9.6A5.6 5.6 0 0 1 6.4 3a5.6 5.6 0 1 0 6.6 6.6",
  panel: "M2.5 3.5h11v9h-11zM6.5 3.5v9",
  desktop: "M2 3.5h12v7.5H2zM6 13.5h4M8 11v2.5",
  tablet: "M4 2.5h8v11H4zM7 11.8h2",
  mobile: "M5 2.5h6v11H5zM7 11.8h2",
  refresh: "M13 8a5 5 0 1 1-1.7-3.8M13 2.6V5h-2.4",
  external: "M9 3.5h3.5V7M12 4 7.5 8.5M12 9.5v3h-9v-9h3",
  code: "m5.5 5.5-3 2.5 3 2.5m5-5 3 2.5-3 2.5M9.5 3.5l-3 9",
  eye: "M1.8 8S4 4.3 8 4.3 14.2 8 14.2 8 12 11.7 8 11.7 1.8 8 1.8 8m6.2 1.8A1.8 1.8 0 1 0 8 6.2a1.8 1.8 0 0 0 0 3.6",
  file: "M4 2.5h5l3 3v10H4zM9 2.5V6h3",
  folder: "M2 4.2h4l1.2 1.6H14v7.6H2z",
  contract: "M4 2.5h8v11H4zM6 6h4M6 8.5h4M6 11h2",
  race: "M3.5 13V3h9l-2 2.5 2 2.5h-9",
  settings: "M2.5 5.5h2.2M7.2 5.5h6.3M2.5 10.5h6.3M11.3 10.5h2.2M6 3.9v3.2M10 8.9v3.2",
  gauge: "M2.6 11.5a6 6 0 1 1 10.8 0M8 8l2.6-2.2",
  logout: "M6.5 13.5H3v-11h3.5M9.5 5 12.5 8l-3 3M6 8h6.5",
  alert: "M8 3 1.8 13.2h12.4zM8 6.6v3M8 11.2v.6",
  sparkle: "M8 2.2 9.3 6 13 7.3 9.3 8.6 8 12.4 6.7 8.6 3 7.3 6.7 6zM12.6 11.2l.5 1.4 1.4.5-1.4.5-.5 1.4-.5-1.4-1.4-.5 1.4-.5z",
  stop: "M4.5 4.5h7v7h-7z",
};

type IconProps = {
  name: IconName;
  size?: number;
  className?: string;
};

export function Icon({ name, size = 16, className = "" }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.3"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className={`shrink-0 ${className}`}
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
