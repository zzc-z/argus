"use client";

import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import styles from "./index.module.css";

export interface TraceIdBarProps {
  traceId: string;
  clusterNode: string;
}

/**
 * Copyable trace-id pill. Click → write trace id to clipboard,
 * swap the "点击复制" notice to "已复制" for 2 seconds.
 */
export function TraceIdBar({ traceId, clusterNode }: TraceIdBarProps) {
  const [copied, setCopied] = React.useState(false);

  const handleCopy = React.useCallback(async () => {
    if (typeof navigator === "undefined" || !navigator.clipboard) return;
    try {
      await navigator.clipboard.writeText(traceId);
    } catch {
      // Clipboard API can reject in some browsers — silent fallback per design.
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  }, [traceId]);

  const handleKeyDown = React.useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        void handleCopy();
      }
    },
    [handleCopy]
  );

  return (
    <div className={styles.row}>
      <div
        role="button"
        tabIndex={0}
        onClick={handleCopy}
        onKeyDown={handleKeyDown}
        className={styles.pill}
      >
        <span className={styles.dot} aria-hidden="true" />
        <span className={`${styles.trace} font-code text-on-surface`}>
          Trace ID:{" "}
          <span className={styles.traceId}>{traceId}</span>
        </span>
        <span className={`${styles.sep} font-label-sm text-outline-variant`}>·</span>
        <span
          className={`${styles.copyNotice} font-label-sm ${
            copied ? "text-primary" : "text-secondary group-hover:text-primary"
          }`}
        >
          <IconSpan
            name={copied ? "check" : "content_copy"}
            size={13}
            className={copied ? "text-primary" : undefined}
          />
          <span>{copied ? "已复制" : "点击复制"}</span>
        </span>
        <span className={`${styles.sep} font-label-sm text-outline-variant`}>·</span>
        <span className={`${styles.node} font-code text-tertiary`}>
          节点: {clusterNode}
        </span>
      </div>
    </div>
  );
}
