"use client";

import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import { cn } from "@/lib/utils";
import type { Source } from "../../mock";
import styles from "./index.module.css";

export interface SourcesPanelProps {
  sources: Source[];
  totalCount: number;
  onViewAll?: () => void;
  /** Optional id of the highlighted source (e.g. clicked citation). */
  highlightedId?: string;
}

/**
 * Right-drawer "Cited Sources" panel. Pure presentation — parent owns
 * the source list and the "view all" navigation.
 */
export function SourcesPanel({
  sources,
  totalCount,
  onViewAll,
  highlightedId,
}: SourcesPanelProps) {
  return (
    <div className={styles.card}>
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <IconSpan name="fact_check" size={20} className="text-primary" />
          <span className={cn(styles.title, "font-headline-sm")}>
            引用源溯源 (Cited Sources)
          </span>
        </div>
        <span className={cn(styles.countChip, "font-code")}>
          {totalCount} 篇已收录
        </span>
      </header>

      <p className={cn(styles.lead, "font-body-sm")}>
        所有结论均经跨信源语义对齐与事实核查验证，支持即时回溯：
      </p>

      <div className={styles.list}>
        {sources.map((s) => (
          <a
            key={s.id}
            href="#"
            className={cn(
              styles.item,
              "group",
              highlightedId === s.id && styles.itemHighlighted
            )}
          >
            <div className={styles.itemTop}>
              <span className={cn(styles.itemCategory, "font-label-sm")}>
                {s.indexLabel} {s.category}
              </span>
              <div className={cn(styles.itemScore, "font-code")}>
                <span className={styles.authority}>权威度 {s.authority}</span>
                <span className={styles.scoreSep}>·</span>
                <span className={styles.match}>匹配 {s.matchPct}%</span>
              </div>
            </div>
            <span className={cn(styles.itemTitle, "font-body-sm")}>{s.title}</span>
            <div className={cn(styles.itemFoot, "font-label-sm")}>
              <span>{s.author}</span>
              <IconSpan
                name="open_in_new"
                size={14}
                className="text-secondary group-hover:text-primary"
              />
            </div>
          </a>
        ))}
      </div>

      <button
        type="button"
        className={cn(styles.viewAllBtn, "font-label-sm")}
        onClick={onViewAll}
      >
        查看全部 {totalCount} 篇来源及引用图谱
      </button>
    </div>
  );
}
