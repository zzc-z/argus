"use client";

import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import {
  CITATION_SCALES,
  CONFIDENCE_LABEL,
  CONFIDENCE_NOTE,
  CONFIDENCE_VALUE,
  FILTER_CITATION_TITLE,
  FILTER_DRAWER_RESET,
  FILTER_DRAWER_TITLE,
  FILTER_STATUS_TITLE,
  FILTER_TIMEFRAME_TITLE,
  FILTER_TOPIC_TITLE,
  PIPELINE_STATUSES,
  TIMEFRAME_OPTIONS,
  TOPIC_FILTERS,
} from "../../mock";
import styles from "./index.module.css";

export interface FilterDrawerProps {
  /** Active timeframe id. */
  activeTimeframeId: string;
  onTimeframeChange: (id: string) => void;
  /** Checked topic ids. */
  checkedTopicIds: ReadonlySet<string>;
  onTopicToggle: (id: string) => void;
  /** Active citation scale id. */
  activeCitationId: string;
  onCitationChange: (id: string) => void;
  /** Checked pipeline status ids. */
  checkedStatusIds: ReadonlySet<string>;
  onStatusToggle: (id: string) => void;
  onReset: () => void;
}

/**
 * Multi-dimensional filter drawer (timeframe / topics / citation / status / confidence).
 * State controlled by page.tsx.
 */
export function FilterDrawer({
  activeTimeframeId,
  onTimeframeChange,
  checkedTopicIds,
  onTopicToggle,
  activeCitationId,
  onCitationChange,
  checkedStatusIds,
  onStatusToggle,
  onReset,
}: FilterDrawerProps) {
  return (
    <aside className={styles.root}>
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <IconSpan name="filter_alt" size={18} className={styles.headerIcon} />
          <span className={styles.title}>{FILTER_DRAWER_TITLE}</span>
        </div>
        <button type="button" className={styles.reset} onClick={onReset}>
          {FILTER_DRAWER_RESET}
        </button>
      </div>

      {/* Timeframe */}
      <div className={styles.group}>
        <span className={styles.groupLabel}>{FILTER_TIMEFRAME_TITLE}</span>
        <div className={styles.timeframeGrid}>
          {TIMEFRAME_OPTIONS.map((t) => {
            const active = t.id === activeTimeframeId;
            return (
              <button
                key={t.id}
                type="button"
                className={`${styles.timeframeBtn} ${active ? styles.timeframeBtnActive : ""}`}
                onClick={() => onTimeframeChange(t.id)}
              >
                {t.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Topics */}
      <div className={styles.group}>
        <span className={styles.groupLabel}>{FILTER_TOPIC_TITLE}</span>
        <div className={styles.topicList}>
          {TOPIC_FILTERS.map((topic) => {
            const checked = checkedTopicIds.has(topic.id);
            return (
              <label key={topic.id} className={styles.topicItem}>
                <span className={styles.topicItemLeft}>
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => onTopicToggle(topic.id)}
                    className={styles.topicCheckbox}
                  />
                  <span className={styles.topicLabel}>{topic.label}</span>
                </span>
                <span className={styles.topicCount}>{topic.count}</span>
              </label>
            );
          })}
        </div>
      </div>

      {/* Citation scale */}
      <div className={styles.group}>
        <span className={styles.groupLabel}>{FILTER_CITATION_TITLE}</span>
        <div className={styles.citationRow}>
          {CITATION_SCALES.map((c) => {
            const active = c.id === activeCitationId;
            return (
              <span
                key={c.id}
                className={`${styles.citationPill} ${active ? styles.citationPillActive : ""}`}
                onClick={() => onCitationChange(c.id)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onCitationChange(c.id);
                  }
                }}
              >
                {c.label}
              </span>
            );
          })}
        </div>
      </div>

      {/* Pipeline status */}
      <div className={styles.group}>
        <span className={styles.groupLabel}>{FILTER_STATUS_TITLE}</span>
        <div className={styles.statusList}>
          {PIPELINE_STATUSES.map((s) => {
            const checked = checkedStatusIds.has(s.id);
            return (
              <label key={s.id} className={styles.statusItem}>
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => onStatusToggle(s.id)}
                  className={styles.statusCheckbox}
                />
                <span>{s.label}</span>
              </label>
            );
          })}
        </div>
      </div>

      {/* Confidence */}
      <div className={styles.confidence}>
        <div className={styles.confidenceRow}>
          <span className={styles.confidenceLabel}>{CONFIDENCE_LABEL}</span>
          <span className={styles.confidenceValue}>{CONFIDENCE_VALUE}</span>
        </div>
        <div className={styles.confidenceBar}>
          <div className={styles.confidenceBarFill} />
        </div>
        <span className={styles.confidenceNote}>{CONFIDENCE_NOTE}</span>
      </div>
    </aside>
  );
}