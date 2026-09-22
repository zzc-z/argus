"use client";

import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import { KbdHint } from "@/components/common/KbdHint";
import styles from "./index.module.css";

type RetryPhase = "idle" | "scheduling" | "done";

export interface ActionGroupProps {
  /** Optional click handler invoked when the user clicks "返回研究看板". */
  onBackToDashboard?: () => void;
  /** Optional click handler invoked when the user opens the global search modal. */
  onSearchTopics?: () => void;
}

/**
 * Three action buttons: primary (Back to Dashboard, ⌘H), secondary (Search ⌘K),
 * tertiary (Retry pipeline). The retry button has its own animation phase.
 */
export function ActionGroup({ onBackToDashboard, onSearchTopics }: ActionGroupProps) {
  const [phase, setPhase] = React.useState<RetryPhase>("idle");

  const handleRetry = React.useCallback(() => {
    if (phase !== "idle") return;
    setPhase("scheduling");
    window.setTimeout(() => {
      setPhase("done");
      window.setTimeout(() => {
        if (typeof window !== "undefined") window.location.reload();
      }, 800);
    }, 1800);
  }, [phase]);

  return (
    <div className={styles.group}>
      <button
        type="button"
        onClick={onBackToDashboard}
        className={`${styles.btn} ${styles.primary}`}
      >
        <IconSpan name="space_dashboard" size={18} />
        <span className="font-headline-sm">返回研究看板</span>
        <KbdHint tone="dark" className={styles.kbdOnDark}>⌘H</KbdHint>
      </button>

      <button
        type="button"
        onClick={onSearchTopics}
        className={`${styles.btn} ${styles.secondary}`}
      >
        <IconSpan name="search" size={18} />
        <span className="font-headline-sm">全局检索研究课题</span>
        <KbdHint tone="light" className={styles.kbdOnLight}>⌘K</KbdHint>
      </button>

      <button
        type="button"
        id="retryButton"
        onClick={handleRetry}
        disabled={phase !== "idle"}
        className={`${styles.btn} ${styles.tertiary} ${
          phase === "done" ? styles.tertiaryDone : ""
        }`}
      >
        <IconSpan
          name="refresh"
          size={18}
          className={phase === "scheduling" ? styles.spin : undefined}
        />
        <span className="font-headline-sm" id="retryLabel">
          {phase === "scheduling"
            ? "正在重新编排智能体..."
            : phase === "done"
              ? "重调度完成，重定向中..."
              : "重新调度执行智能体"}
        </span>
      </button>
    </div>
  );
}
