import { statusPresentation, type StatusKind } from "@/lib/order-journey";
import styles from "./status-badge.module.css";

export function StatusBadge({
  kind,
  status,
}: {
  kind: StatusKind;
  status: string;
}) {
  const presentation = statusPresentation(kind, status);
  return (
    <span className={styles.badge} data-tone={presentation.tone}>
      <span className={styles.dot} aria-hidden="true" />
      {presentation.label}
    </span>
  );
}
