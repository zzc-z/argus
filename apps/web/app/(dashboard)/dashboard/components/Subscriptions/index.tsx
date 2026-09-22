import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import { cn } from "@/lib/utils";
import type { Subscription } from "../../mock";
import styles from "./index.module.css";

export interface SubscriptionsProps {
  items: Subscription[];
}

/**
 * Subscriptions list card — each row: icon-box (purple tint for unread / grey for paused)
 * + title + badge (right top) + updated/source (left body, stacked) + pause/play btn (right bottom).
 */
export function Subscriptions({ items }: SubscriptionsProps) {
  return (
    <section className={styles.root}>
      <header className={styles.head}>
        <div className={styles.headTitle}>
          <IconSpan name="bookmark" size={18} className="text-primary-container" />
          <h2 className={`${styles.title} font-headline-sm font-semibold tracking-tight`}>
            我的主题订阅
          </h2>
        </div>
        <button type="button" className={`${styles.addBtn} font-label-sm font-medium`}>
          <IconSpan name="add" size={14} />
          <span>新增订阅</span>
        </button>
      </header>

      <ul className={styles.list}>
        {items.map((s) => (
          <li
            key={s.id}
            className={cn(
              styles.item,
              s.paused && styles.itemPaused
            )}
          >
            <div className={cn(styles.iconBox, !s.paused && styles.iconBoxActive)}>
              <IconSpan
                name={s.paused ? "pause_circle" : "bookmarks"}
                size={18}
                className={s.paused ? "text-secondary" : "text-primary-container"}
              />
            </div>
            <div className={styles.body}>
              <p className={`${styles.itemTitle} font-body-sm font-medium`}>{s.title}</p>
              <p className={`${styles.itemUpdated} font-label-sm`}>{s.updatedAt}</p>
              <p className={`${styles.itemSource} font-label-sm`}>{s.source}</p>
            </div>
            <div className={styles.right}>
              <span
                className={cn(
                  styles.badge,
                  s.badgeTone === "unread" && styles.badgeUnread,
                  s.badgeTone === "none" && styles.badgeNone,
                  s.badgeTone === "paused" && styles.badgePaused
                )}
              >
                {s.badgeText}
              </span>
              <button
                type="button"
                className={`${styles.toggleBtn} font-label-sm`}
                aria-label={s.paused ? "恢复订阅" : "暂停订阅"}
              >
                {s.paused ? "恢复" : "暂停"}
              </button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}