"use client";

import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import {
  CTA_FILTER_LABEL,
  CTA_NEW_RESEARCH_LABEL,
  CTA_NEW_RESEARCH_SHORTCUT,
  PAGE_DAG_STATUS,
  PAGE_SUBTITLE_MID,
  PAGE_SUBTITLE_PREFIX,
  PAGE_SUBTITLE_REPORT_COUNT,
  PAGE_SUBTITLE_TRACK_COUNT,
  PAGE_SUBTITLE_TRACK_PREFIX,
  PAGE_SUBTITLE_TRACK_SUFFIX,
  PAGE_TITLE,
  PAGE_TITLE_EN,
} from "../../mock";
import styles from "./index.module.css";

export interface ReportsHeaderProps {
  filterBadgeVisible: boolean;
  onToggleFilters: () => void;
  onNewResearch: () => void;
}

/**
 * Page title block ("研究报告库" + summary stats) + top CTAs
 * (多维筛选 + 发起新研究). Action handlers owned by page.tsx.
 */
export function ReportsHeader({
  filterBadgeVisible,
  onToggleFilters,
  onNewResearch,
}: ReportsHeaderProps) {
  return (
    <header className={styles.root}>
      <div className={styles.titleBlock}>
        <div className={styles.titleRow}>
          <h1 className={styles.title}>{PAGE_TITLE}</h1>
          <span className={styles.titleEn}>{PAGE_TITLE_EN}</span>
        </div>
        <p className={styles.subtitle}>
          <span>{PAGE_SUBTITLE_PREFIX}</span>
          <span className={styles.subtitleNum}>{PAGE_SUBTITLE_REPORT_COUNT}</span>
          <span>{PAGE_SUBTITLE_MID}</span>
          <span className={styles.subtitleDot}>·</span>
          <span>{PAGE_SUBTITLE_TRACK_PREFIX}</span>
          <span className={styles.subtitleNum}>{PAGE_SUBTITLE_TRACK_COUNT}</span>
          <span>{PAGE_SUBTITLE_TRACK_SUFFIX}</span>
          <span className={styles.subtitleDot}>·</span>
          <span className={styles.dagStatus}>
            <span className={styles.dagDot} />
            {PAGE_DAG_STATUS}
          </span>
        </p>
      </div>

      <div className={styles.actions}>
        <button
          type="button"
          className={styles.filterBtn}
          onClick={onToggleFilters}
          aria-label={CTA_FILTER_LABEL}
        >
          <IconSpan name="tune" size={18} className={styles.filterBtnIcon} />
          <span>{CTA_FILTER_LABEL}</span>
          {filterBadgeVisible && <span className={styles.filterBadge} />}
        </button>
        <button
          type="button"
          className={styles.primaryBtn}
          onClick={onNewResearch}
        >
          <IconSpan name="add" size={18} />
          <span className={styles.primaryBtnLabel}>{CTA_NEW_RESEARCH_LABEL}</span>
          <span className={styles.primaryBtnKbd}>{CTA_NEW_RESEARCH_SHORTCUT}</span>
        </button>
      </div>
    </header>
  );
}