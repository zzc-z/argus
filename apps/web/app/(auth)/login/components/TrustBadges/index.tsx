import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import styles from "./index.module.css";

const BADGES = [
  { icon: "verified_user", label: "端到端隔离环境" },
  { icon: "bolt", label: "零保留模型训练" },
  { icon: "security", label: "SOC2 Type II 审计中" },
] as const;

/**
 * Bottom-left three trust micro-badges. Single source for the row,
 * rendered as a flex with / separators (semantic delimiter, not a control).
 */
export function TrustBadges() {
  return (
    <footer className={`${styles.root} font-label-sm text-secondary`}>
      {BADGES.map((b, i) => (
        <React.Fragment key={b.icon}>
          <div className={styles.badge}>
            <IconSpan name={b.icon} size={15} className="text-primary-container" />
            <span>{b.label}</span>
          </div>
          {i < BADGES.length - 1 && (
            <span className={styles.sep}>/</span>
          )}
        </React.Fragment>
      ))}
    </footer>
  );
}