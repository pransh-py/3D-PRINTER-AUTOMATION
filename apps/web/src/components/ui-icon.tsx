type IconName =
  | "arrow"
  | "arrow-up"
  | "upload"
  | "cube"
  | "check"
  | "chevron"
  | "layers"
  | "file";

const paths: Record<IconName, string> = {
  arrow: "M4 12h15m-6-6 6 6-6 6",
  "arrow-up": "M6 18 18 6M6 6h12v12",
  upload: "M12 16V3m-5 5 5-5 5 5M4 15v5a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-5",
  cube: "m12 3 9 5v9l-9 5-9-5V8l9-5Zm0 10 9-5M3 8l9 5m0 0v9",
  check: "m5 12 4 4L19 6",
  chevron: "m6 9 6 6 6-6",
  layers: "m12 3 10 6-10 6L2 9l10-6ZM2 13l10 6 10-6M2 17l10 6 10-6",
  file: "M14 2H5a1 1 0 0 0-1 1v18a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V8l-6-6Zm0 0v6h6M8 13h8m-8 4h5",
};

export function UiIcon({
  name,
  className,
}: {
  name: IconName;
  className?: string;
}) {
  return (
    <svg
      className={className}
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name]} />
    </svg>
  );
}
