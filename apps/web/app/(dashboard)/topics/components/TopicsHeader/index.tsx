"use client";

import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import styles from "./index.module.css";

export interface TopicsHeaderProps {
  /** Total topics configured (subtitle: "已配置 N 个研究课题监控"). */
  totalTopics?: number;
  /** Total sources ingested (subtitle: "已接入 N 个全网权威数据源"). */
  totalSources?: number;
  /** Probe success rate printed in the quick-peek pill. */
  successRate?: string;
}

/**
 * Top banner: eyebrow tag + H1 + subtitle + CTA / success-rate pill.
 * Owns the right-aligned "新建研究订阅" button — it dispatches a custom event
 * that `FilterBar` and `NewSubscriptionDrawer` listen for to open the drawer
 * (lets multiple triggers share one modal without prop-drilling).
 */
export function TopicsHeader({
  totalTopics = 7,
  totalSources = 847,
  successRate = "99.82%",
}: TopicsHeaderProps) {
  const openDrawer = React.useCallback(() => {
    window.dispatchEvent(new CustomEvent("argus:topics:open-drawer"));
  }, []);

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const tag = target?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      if ((e.metaKey || e.ctrlKey) && (e.key === "n" || e.key === "N")) {
        e.preventDefault();
        openDrawer();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openDrawer]);

  return (
    <section className={styles.root}>
      <div className={styles.copy}>
        <div className={styles.eyebrow}>
          <span className={`${styles.eyebrowTag} font-code`}>AGENT WORKSPACE // DAEMON-SUBS</span>
          <span className={styles.eyebrowSep}>·</span>
          <span className={styles.eyebrowNote}>DAG Cluster 巡检引擎已联机</span>
        </div>
        <h1 className={`${styles.title} font-headline-xl tracking-tight text-on-surface`}>
          主题订阅管理 (Topic Subscriptions)
        </h1>
        <p className={`${styles.subtitle} font-body-md text-secondary`}>
          当前已配置 <span className="font-code font-semibold text-on-surface">{totalTopics}</span> 个研究课题监控，已接入{" "}
          <span className="font-code font-semibold text-on-surface">{totalSources}</span> 个全网权威数据源与 RSS 高置信度流
        </p>
      </div>

      <div className={styles.actions}>
        <div className={styles.successPill}>
          <div className={styles.successText}>
            <span className="font-label-sm uppercase tracking-wider text-secondary">巡检成功率</span>
            <span className={`${styles.successValue} font-code`}>{successRate}</span>
          </div>
          <div className={styles.successIcon}>
            <IconSpan name="verified" size={18} className="text-primary" />
          </div>
        </div>
        <button type="button" className={styles.cta} onClick={openDrawer}>
          <IconSpan name="add" size={18} />
          <span>新建研究订阅</span>
          <kbd className={`${styles.ctaKbd} font-code`}>⌘N</kbd>
        </button>
      </div>
    </section>
  );
}
