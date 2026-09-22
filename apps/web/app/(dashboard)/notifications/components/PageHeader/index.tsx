"use client";

import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import styles from "./index.module.css";

export interface PageHeaderProps {
  unreadCount: number;
  onMarkAll: () => void;
}

/**
 * Top breadcrumb + page title + right-side actions.
 * 1:1 extracted from argus_notifications/code.html lines 6-36.
 */
export function PageHeader({ unreadCount, onMarkAll }: PageHeaderProps) {
  return (
    <header className={styles.root}>
      <div className={styles.left}>
        <div className={styles.breadcrumb}>
          <span className={styles.crumb}>控制台</span>
          <IconSpan name="chevron_right" size={14} className={styles.crumbIcon} />
          <span className={styles.path}>/notifications</span>
          <span className={styles.liveChip}>
            <span className={styles.liveDot} />
            <span className={styles.liveChipText}>REALTIME_STREAM: ACTIVE</span>
          </span>
        </div>
        <div className={styles.titleRow}>
          <h1 className={`${styles.title} font-headline-lg font-semibold tracking-tight`}>
            通知中心 / Notifications
          </h1>
          <span className={`${styles.subtitle} font-label-md font-code`}>
            [{unreadCount} 新事件待处理]
          </span>
        </div>
        <p className={`${styles.desc} font-body-sm`}>
          查看主题监控动态、智能体研报交付与知识图谱演进通知
        </p>
      </div>

      <div className={styles.right}>
        <button type="button" className={styles.markAllBtn} onClick={onMarkAll}>
          <IconSpan name="done_all" size={16} className={styles.markAllIcon} />
          <span>全部标为已读</span>
        </button>
        <button type="button" className={styles.iconBtn} title="通知设置">
          <IconSpan name="tune" size={18} />
        </button>
        <button type="button" className={styles.iconBtn} title="导出日志">
          <IconSpan name="download" size={18} />
        </button>
      </div>
    </header>
  );
}