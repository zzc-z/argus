"use client";

import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import styles from "./index.module.css";

export interface BulkActionToolbarProps {
  selectedCount: number;
  /** Total items currently visible to the user (used for select-all checkbox state). */
  totalVisible: number;
  /** Whether all currently-visible items are selected. */
  allVisibleSelected: boolean;
  onToggleSelectAll: () => void;
  onMarkAsRead: () => void;
  onMute: () => void;
  onClear: () => void;
}

/**
 * Floating bulk-action row (visual hint + 3 actions).
 * 1:1 extracted from argus_notifications/code.html lines 81-105.
 *
 * Disabled visual (opacity-40) when selectedCount === 0.
 */
export function BulkActionToolbar({
  selectedCount,
  totalVisible,
  allVisibleSelected,
  onToggleSelectAll,
  onMarkAsRead,
  onMute,
  onClear,
}: BulkActionToolbarProps) {
  const disabled = selectedCount === 0;
  const wrapperClass = `${styles.bar} ${disabled ? styles.disabled : ""}`;
  const checkboxState: boolean | "indeterminate" = allVisibleSelected
    ? true
    : selectedCount > 0
    ? "indeterminate"
    : false;

  return (
    <div className={wrapperClass}>
      <div className={styles.left}>
        <label className={styles.selectAll}>
          <input
            type="checkbox"
            className={styles.checkbox}
            checked={checkboxState === true}
            ref={(el) => {
              if (el) el.indeterminate = checkboxState === "indeterminate";
            }}
            onChange={onToggleSelectAll}
            disabled={totalVisible === 0}
          />
          <span className={`${styles.label} font-headline-sm font-semibold`}>
            已选中{" "}
            <span className={`${styles.count} font-code`}>{selectedCount}</span> 项
          </span>
        </label>
        <span className={`${styles.sep} font-code`}>|</span>
        <span className={`${styles.hint} font-label-sm hidden sm:inline`}>
          批量操作将同步至分析集群及协同缓存
        </span>
      </div>

      <div className={styles.right}>
        <button type="button" className={styles.action} onClick={onMarkAsRead}>
          <IconSpan name="mark_chat_read" size={16} className={styles.actionIconPrimary} />
          <span>标为已读</span>
        </button>
        <button type="button" className={styles.action} onClick={onMute}>
          <IconSpan name="notifications_paused" size={16} className={styles.actionIcon} />
          <span className={styles.hideOnSmall}>静音此订阅源</span>
        </button>
        <button type="button" className={styles.actionDanger} onClick={onClear}>
          <IconSpan name="close" size={16} className={styles.actionIcon} />
          <span>清空</span>
        </button>
      </div>
    </div>
  );
}