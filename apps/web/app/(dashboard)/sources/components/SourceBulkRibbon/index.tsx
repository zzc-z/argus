"use client";

import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import styles from "./index.module.css";

export interface SourceBulkRibbonProps {
  selectedCount: number;
  allChecked: boolean;
  indeterminate: boolean;
  onToggleAll: () => void;
}

/**
 * Floating selection ribbon above the table — select-all + bulk actions.
 * Actions are disabled when no selection (matches design intent).
 */
export function SourceBulkRibbon({
  selectedCount,
  allChecked,
  indeterminate,
  onToggleAll,
}: SourceBulkRibbonProps) {
  const disabled = selectedCount === 0;

  return (
    <div className={styles.ribbon}>
      <div className={styles.left}>
        <div className={styles.selectAll}>
          <input
            id="select-all"
            type="checkbox"
            checked={allChecked}
            ref={(el) => {
              if (el) el.indeterminate = indeterminate;
            }}
            onChange={onToggleAll}
            className={`${styles.checkbox} accent-primary-container`}
          />
          <label htmlFor="select-all" className={`${styles.label} font-body-sm`}>
            全选当前列表 (
            <span className={`${styles.count} font-code`}>{selectedCount}</span>
            项)
          </label>
        </div>
        <div className={`${styles.sep} hidden sm:block`} />
        <span className={`${styles.hint} font-label-sm hidden sm:inline-block`}>
          批量操作工具箱
        </span>
      </div>

      <div className={styles.actions}>
        <button type="button" className={`${styles.actionBtn} font-body-sm`} disabled={disabled}>
          <IconSpan name="refresh" size={16} />
          <span>重新切片</span>
        </button>
        <button type="button" className={`${styles.actionBtn} font-body-sm`} disabled={disabled}>
          <IconSpan name="folder_special" size={16} />
          <span>加入专题</span>
        </button>
        <button
          type="button"
          className={`${styles.actionBtn} ${styles.actionBtnDanger} font-body-sm`}
          disabled={disabled}
        >
          <IconSpan name="delete" size={16} />
          <span>批量删除</span>
        </button>
      </div>
    </div>
  );
}