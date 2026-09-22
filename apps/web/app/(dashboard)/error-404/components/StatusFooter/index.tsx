import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import styles from "./index.module.css";

export interface StatusFooterProps {
  latencyMs: number;
  clusterHealthPct: number;
  dataStateNote: string;
}

/**
 * Bottom row showing latency, cluster health, data state, and a link to the status page.
 */
export function StatusFooter({
  latencyMs,
  clusterHealthPct,
  dataStateNote,
}: StatusFooterProps) {
  return (
    <div className={styles.row}>
      <div className={styles.left}>
        <span className={styles.dataState}>
          <IconSpan name="format_image_left" size={14} />
          <span>数据状态：{dataStateNote}</span>
        </span>
      </div>
      <div className={`${styles.right} font-code`}>
        <span>Latency: {latencyMs}ms</span>
        <span className={styles.sep}>·</span>
        <span>Cluster: {clusterHealthPct.toFixed(2)}% Healthy</span>
        <span className={styles.sep}>·</span>
        <a className={styles.statusLink} href="#status-page">
          系统状态页
        </a>
      </div>
    </div>
  );
}
