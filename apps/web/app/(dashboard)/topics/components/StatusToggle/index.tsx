"use client";

import * as React from "react";
import styles from "./index.module.css";

export interface StatusToggleProps {
  checked: boolean;
  onChange: (next: boolean) => void;
  checkedLabel?: string;
  uncheckedLabel?: string;
}

/**
 * Two-state subscription switch — visually identical to the peer-style toggle
 * in argus_topics/code.html row 5 (`.peer-checked:after:translate-x-full`).
 *
 * Controlled — owns no state. Listens for change events and bubbles the new
 * boolean up to the parent.
 */
export function StatusToggle({
  checked,
  onChange,
  checkedLabel = "运行中",
  uncheckedLabel = "已停用",
}: StatusToggleProps) {
  return (
    <label className={styles.wrap}>
      <input
        type="checkbox"
        className={styles.input}
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className={`${styles.track} ${checked ? styles.trackOn : ""}`} />
      <span
        className={`${styles.label} font-label-sm ${checked ? styles.labelOn : styles.labelOff}`}
      >
        {checked ? checkedLabel : uncheckedLabel}
      </span>
    </label>
  );
}
