"use client";

import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import { BULK_ACTIONS } from "../../mock";
import styles from "./index.module.css";

export interface BulkActionBarProps {
  visible: boolean;
  count: number;
  onCancel: () => void;
  onAction: (id: string) => void;
}

/**
 * Floating capsule bar that slides up when ≥1 row is selected.
 * Pure presentation; visibility/count driven by page.tsx.
 */
export function BulkActionBar({ visible, count, onCancel, onAction }: BulkActionBarProps) {
  return (
    <div
      className={`${styles.root} ${visible ? styles.visible : styles.hidden}`}
      aria-hidden={!visible}
    >
      <div className={styles.row}>
        <div className={styles.countGroup}>
          <span className={styles.countDot} />
          <span className={styles.countText}>
            已选择 <span className={styles.countNum}>{count}</span> 篇研报
          </span>
        </div>
        <span className={styles.sep} />
        <div className={styles.actions}>
          {BULK_ACTIONS.map((a) => (
            <button
              key={a.id}
              type="button"
              className={`${styles.actionBtn} ${
                "tone" in a && a.tone === "danger" ? styles.actionDanger : ""
              }`}
              onClick={() => onAction(a.id)}
            >
              <IconSpan name={a.icon} size={16} />
              <span>{a.label}</span>
            </button>
          ))}
        </div>
        <button
          type="button"
          className={styles.cancelBtn}
          onClick={onCancel}
          aria-label="关闭批量操作"
        >
          <IconSpan name="close" size={16} />
        </button>
      </div>
    </div>
  );
}