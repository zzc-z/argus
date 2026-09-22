"use client";

import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import {
  SEARCH_PLACEHOLDER,
  SEARCH_SHORTCUT,
  TOPBAR_STATUS_LABEL,
  TOPBAR_THROUGHPUT,
} from "../../mock";
import styles from "./index.module.css";

/**
 * Fixed top app bar — global search + DAG status pill + actions + user.
 * Pure presentation; search/status are display-only here.
 */
export function TopBar() {
  return (
    <header className={styles.root}>
      <div className={styles.left}>
        {/* Search well */}
        <div className={styles.search}>
          <IconSpan name="search" size={18} className={styles.searchIcon} />
          <span className={styles.searchPlaceholder}>{SEARCH_PLACEHOLDER}</span>
          <kbd className={styles.kbd}>{SEARCH_SHORTCUT}</kbd>
        </div>

        {/* Status pill */}
        <div className={styles.status}>
          <span className={styles.statusDot} />
          <span className={styles.statusLabel}>{TOPBAR_STATUS_LABEL}</span>
          <span className={styles.statusSep}>·</span>
          <span className={styles.statusThroughput}>{TOPBAR_THROUGHPUT}</span>
        </div>
      </div>

      <div className={styles.right}>
        <button type="button" className={styles.iconBtn} aria-label="通知">
          <IconSpan name="notifications" size={20} />
          <span className={styles.iconBtnDot} />
        </button>
        <button type="button" className={styles.iconBtn} aria-label="帮助">
          <IconSpan name="help_outline" size={20} />
        </button>
        <span className={styles.sep} aria-hidden="true" />
        <div className={styles.user}>
          <div className={styles.userText}>
            <span className={styles.userName}>Thomas Lin</span>
            <span className={styles.userRole}>Lead Researcher</span>
          </div>
          <div className={styles.avatar}>
            <IconSpan name="person" size={18} />
          </div>
        </div>
      </div>
    </header>
  );
}