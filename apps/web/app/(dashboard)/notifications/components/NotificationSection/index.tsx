"use client";

import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import { NotificationItem } from "../NotificationItem";
import type { NotificationSection as Section, NotificationWithMeta } from "../../mock";
import styles from "./index.module.css";

export interface NotificationSectionProps {
  section: Section;
  expanded: boolean;
  onToggleExpand: () => void;
  selectedIds: Set<string>;
  onToggleItem: (id: string) => void;
  onMarkRead: (id: string) => void;
  /** Optional per-item filter; section hides itself when no items match. */
  filterItem?: (item: NotificationWithMeta) => boolean;
}

/**
 * Grouped section — title bar + items container.
 * 1:1 extracted from argus_notifications/code.html (sections today/yesterday/earlier).
 *
 * The "Earlier" section is collapsible; the page owns its expand state.
 */
export function NotificationSection({
  section,
  expanded,
  onToggleExpand,
  selectedIds,
  onToggleItem,
  onMarkRead,
  filterItem,
}: NotificationSectionProps) {
  const visible = filterItem ? section.items.filter(filterItem) : section.items;
  const isCollapsible = section.title.includes("更早");
  const showItems = !isCollapsible || expanded;

  if (visible.length === 0) return null;

  return (
    <section className={styles.section}>
      <div className={styles.header}>
        <div className={styles.titleWrap}>
          {section.live && <span className={styles.liveDot} />}
          <h2 className={`${styles.title} font-headline-sm font-semibold`}>{section.title}</h2>
          <span className={`${styles.count} font-code`}>{section.count}</span>
        </div>
        <div className={styles.headerRight}>
          {section.tail && (
            <span className={`${styles.tail} font-code`}>{section.tail}</span>
          )}
          {isCollapsible && (
            <button type="button" className={`${styles.expand} font-body-sm`} onClick={onToggleExpand}>
              <span>{expanded ? "收起历史列表" : "展开历史列表"}</span>
              <IconSpan name={expanded ? "expand_less" : "expand_more"} size={14} />
            </button>
          )}
        </div>
      </div>

      {showItems && (
        <div className={styles.items}>
          {visible.map((item) => (
            <NotificationItem
              key={item.id}
              item={item}
              selected={selectedIds.has(item.id)}
              onToggle={() => onToggleItem(item.id)}
              onMarkRead={() => onMarkRead(item.id)}
            />
          ))}
        </div>
      )}
    </section>
  );
}