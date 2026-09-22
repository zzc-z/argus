import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import type { Kpi } from "../../mock";
import styles from "./index.module.css";

export interface KpiCardProps {
  kpi: Kpi;
}

/**
 * Single KPI tile — value + sub + footer (icon + highlight number) + bottom progress.
 * Card surface follows shadcn Card; spacing/colors come from 47-token.
 */
export function KpiCard({ kpi }: KpiCardProps) {
  return (
    <div className={styles.root}>
      <div className={styles.head}>
        <div className={styles.iconBox}>
          <IconSpan name={kpi.icon} size={18} className="text-primary-container" />
        </div>
        <p className={`${styles.label} font-label-sm font-medium`}>{kpi.label}</p>
      </div>

      <div className={styles.valueRow}>
        <span className={`${styles.value} font-headline-lg font-semibold tracking-tight`}>
          {kpi.value}
        </span>
        <span className={`${styles.sub} font-label-sm`}>{kpi.sub}</span>
      </div>

      <div className={styles.footer}>
        <IconSpan
          name={kpi.footerIcon}
          size={14}
          className={kpi.footerIconTone === "success" ? styles.success : kpi.footerIconTone === "primary" ? styles.primary : styles.secondary}
        />
        <p className={`${styles.footerText} font-label-sm`}>
          {kpi.footerPrefix}
          <span className={styles.highlight}>{kpi.footerHighlight}</span>
          {kpi.footerSuffix}
        </p>
      </div>

      <div className={styles.progressTrack}>
        <div
          className={styles.progressFill}
          style={{ width: `${kpi.progress}%` }}
          aria-hidden="true"
        />
      </div>
    </div>
  );
}