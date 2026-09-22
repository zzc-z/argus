import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import { cn } from "@/lib/utils";
import type { ActivityItem } from "../../mock";
import styles from "./index.module.css";

export interface RecentActivityProps {
  items: ActivityItem[];
}

/**
 * Vertical activity feed card. First item gets a violet highlight (1px inset border).
 * Each row: 40px icon-box + body (title + meta) + right (badge top, timestamp bottom).
 */
export function RecentActivity({ items }: RecentActivityProps) {
  return (
    <section className={styles.root}>
      <header className={styles.head}>
        <div className={styles.headTitle}>
          <IconSpan name="history" size={18} className="text-primary-container" />
          <h2 className={`${styles.title} font-headline-sm font-semibold tracking-tight`}>
            最近活动动态
          </h2>
        </div>
        <button type="button" className={`${styles.viewAll} font-label-sm font-medium`}>
          查看全部
          <IconSpan name="arrow_forward" size={14} />
        </button>
      </header>

      <ol className={styles.list}>
        {items.map((a, i) => (
          <li
            key={a.id}
            className={cn(
              styles.item,
              i === 0 && styles.itemFirst,
              a.highlight && styles.itemHighlight
            )}
          >
            <div
              className={cn(
                styles.iconBox,
                a.iconBox === "primary" && styles.iconBoxPrimary,
                a.iconBox === "accent" && styles.iconBoxAccent
              )}
            >
              <IconSpan name={a.icon} size={18} />
            </div>
            <div className={styles.body}>
              <p className={`${styles.itemTitle} font-body-sm font-medium`}>{a.title}</p>
              <p className={`${styles.itemMeta} font-label-sm`}>{a.meta}</p>
            </div>
            <div className={styles.right}>
              <span
                className={cn(
                  styles.badge,
                  a.badgeTone === "highlight" && styles.badgeHighlight,
                  a.badgeTone === "muted" && styles.badgeMuted,
                  a.badgeTone === "warning" && styles.badgeWarning
                )}
              >
                {a.badgeText}
              </span>
              <span className={`${styles.timestamp} font-label-sm`}>{a.timestamp}</span>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}