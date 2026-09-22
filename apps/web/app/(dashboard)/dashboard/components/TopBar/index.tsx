import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import { KbdHint } from "@/components/common/KbdHint";
import styles from "./index.module.css";

/** Fixed top bar — global search + bell + user. 1:1 extracted from argus_dashboard. */
export function TopBar() {
  return (
    <header className={styles.root}>
      <div className={styles.search}>
        <IconSpan name="search" size={16} className="text-secondary" />
        <input
          type="text"
          placeholder="搜索知识库、研报、节点或配置"
          className={`${styles.searchInput} font-body-sm`}
        />
        <KbdHint tone="light">⌘K</KbdHint>
      </div>

      <div className={styles.actions}>
        <button type="button" className={styles.iconBtn} aria-label="通知">
          <IconSpan name="notifications" size={18} className="text-secondary" />
          <span className={styles.badge}>3</span>
        </button>
        <button type="button" className={styles.iconBtn} aria-label="设置">
          <IconSpan name="settings" size={18} className="text-secondary" />
        </button>
        <div className={styles.divider} aria-hidden="true" />
        <div className={styles.user}>
          <div className={styles.avatar} />
          <div className={styles.userText}>
            <p className={`${styles.userName} font-label-sm font-medium`}>Tony Stark</p>
            <p className={`${styles.userRole} font-label-sm`}>研究主管 · Pro</p>
          </div>
        </div>
      </div>
    </header>
  );
}