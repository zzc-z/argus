import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import { StatusDot } from "@/components/common/StatusDot";
import styles from "./index.module.css";

export interface PageHeaderProps {
  title: string;
  titleChip: string;
  greeting: string;
  date: string;
  statusLabel: string;
  notifications: number;
}

/**
 * Dashboard top-of-main title row.
 * Layout: title + chip + greeting/date (left); status chip + notification btn (right).
 */
export function PageHeader({
  title,
  titleChip,
  greeting,
  date,
  statusLabel,
  notifications,
}: PageHeaderProps) {
  return (
    <div className={styles.root}>
      <div className={styles.left}>
        <div className={styles.titleRow}>
          <h1 className={`${styles.title} font-headline-lg font-semibold tracking-tight`}>
            {title}
          </h1>
          <span className={`${styles.chip} font-label-sm font-medium`}>
            {titleChip}
          </span>
        </div>
        <p className={`${styles.meta} font-body-sm`}>
          {greeting}
          <span className={styles.dot}>·</span>
          {date}
        </p>
      </div>

      <div className={styles.right}>
        <div className={styles.status}>
          <StatusDot color="emerald" ping />
          <span className={`${styles.statusText} font-label-sm font-medium`}>
            {statusLabel}
          </span>
        </div>
        <button type="button" className={styles.notifyBtn} aria-label="通知中心">
          <IconSpan name="notifications" size={16} className="text-primary-container" />
          {notifications > 0 && (
            <span className={`${styles.notifyCount} font-label-sm font-semibold`}>
              {notifications}
            </span>
          )}
        </button>
      </div>
    </div>
  );
}