"use client";

import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import type { Report } from "../../mock";
import styles from "./index.module.css";

export interface ReportRowProps {
  report: Report;
  selected: boolean;
  onToggle: (id: string) => void;
  /** Alternate row banding (every other row gets bg-surface-container-low/20). */
  banded?: boolean;
}

/**
 * One report row in the table view.
 * Star icon, topic badge, generatedAt column, sources count, status pill, action icons.
 * Pure presentation.
 */
export function ReportRow({ report, selected, onToggle, banded }: ReportRowProps) {
  const isRunning = report.status === "running";

  return (
    <div
      className={`${styles.row} ${banded ? styles.banded : ""} ${isRunning ? styles.running : ""}`}
    >
      {/* Col 1: checkbox + title + summary + mobile badges */}
      <div className={`${styles.col} ${styles.colTitle}`}>
        <input
          type="checkbox"
          className={styles.checkbox}
          checked={selected}
          onChange={() => onToggle(report.id)}
          aria-label={`选择 ${report.title}`}
        />
        <div className={styles.titleWrap}>
          <div className={styles.titleLine}>
            {isRunning && <span className={styles.runningDot} aria-hidden="true" />}
            <a className={styles.title} href="#">
              {report.title}
            </a>
            <button
              type="button"
              className={`${styles.star} ${report.starred ? styles.starred : ""}`}
              aria-label={report.starred ? "取消星标" : "星标关注"}
              title={report.starred ? "取消星标" : "星标关注"}
            >
              <IconSpan name="star" size={16} />
            </button>
          </div>
          <p className={styles.summary}>{report.summary}</p>
          <div className={styles.mobileBadges}>
            <span className={styles.mobileBadge}>{report.topic.label}</span>
            {isRunning && report.runningProgress !== undefined ? (
              <span className={styles.mobileRunning}>
                实时生成中 {report.runningProgress}%
              </span>
            ) : (
              <span className={styles.mobileTime}>{report.generatedAt}</span>
            )}
          </div>
        </div>
      </div>

      {/* Col 2: topic badge (desktop) */}
      <div className={`${styles.col} ${styles.colTopic}`}>
        <span className={`${styles.topicBadge} ${styles[`topic-${report.topic.tone}`] ?? ""}`}>
          {report.topic.label}
        </span>
      </div>

      {/* Col 3: generatedAt */}
      <div className={`${styles.col} ${styles.colTime}`}>
        <span className={isRunning ? styles.timePrimary : styles.timeDefault}>
          {report.generatedAt}
        </span>
        <span className={styles.timeSub}>{report.generatedAtSub}</span>
      </div>

      {/* Col 4: sources */}
      <div className={`${styles.col} ${styles.colSources}`}>
        <span className={styles.sources}>{report.sourcesCount} 篇</span>
        <span className={styles.sourcesSub}>{report.viewsCount} 阅</span>
      </div>

      {/* Col 5: status + actions */}
      <div className={`${styles.col} ${styles.colActions}`}>
        {isRunning ? (
          <span className={styles.runningBadge}>
            <IconSpan name="progress_activity" size={13} className={styles.runningBadgeIcon} />
            <span>正在合成 ({report.runningProgress ?? 0}%)</span>
          </span>
        ) : (
          <span className={styles.verifiedBadge}>
            <IconSpan name="check_circle" size={14} />
            <span className={styles.verifiedLabel}>已交叉验证</span>
          </span>
        )}
        <div className={styles.actionGroup}>
          <button
            type="button"
            className={styles.actionBtn}
            aria-label={isRunning ? "查看运行中 DAG 图谱" : "阅读研报"}
            title={isRunning ? "查看运行中 DAG 图谱" : "阅读研报"}
          >
            <IconSpan name={isRunning ? "account_tree" : "visibility"} size={18} />
          </button>
          <button
            type="button"
            className={styles.actionBtn}
            aria-label={isRunning ? "暂停生成" : "导出 PDF"}
            title={isRunning ? "暂停生成" : "导出 PDF"}
          >
            <IconSpan name={isRunning ? "pause" : "download"} size={18} />
          </button>
          <button
            type="button"
            className={styles.actionBtn}
            aria-label="更多选项"
            title="更多选项"
          >
            <IconSpan name="more_horiz" size={18} />
          </button>
        </div>
      </div>
    </div>
  );
}