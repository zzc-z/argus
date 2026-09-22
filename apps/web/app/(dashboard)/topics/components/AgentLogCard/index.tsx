import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import { type AgentLogLine } from "../../mock";
import styles from "./index.module.css";

export interface AgentLogCardProps {
  log: AgentLogLine[];
}

/**
 * Live Argus daemon card — title + PID with a pulsing dot, three live log
 * lines, and a footer showing next-inspection countdown.
 *
 * The countdown decrements client-side from a generous upper bound so the
 * "00:14:48" figure cycles over time and feels alive (no real backend).
 */
export function AgentLogCard({ log }: AgentLogCardProps) {
  const [seconds, setSeconds] = React.useState(14 * 60 + 48);

  React.useEffect(() => {
    const id = window.setInterval(() => {
      setSeconds((s) => (s <= 0 ? 14 * 60 + 48 : s - 1));
    }, 1000);
    return () => window.clearInterval(id);
  }, []);

  const mm = String(Math.floor(seconds / 60)).padStart(2, "0");
  const ss = String(seconds % 60).padStart(2, "0");

  return (
    <article className={styles.card}>
      <div>
        <header className={styles.head}>
          <span className={`${styles.title} font-headline-sm font-semibold`}>
            Argus 巡检守护进程
          </span>
          <span className={`${styles.pid} font-code`}>
            <span className={styles.pidDot} aria-hidden="true" />
            PID: 40921
          </span>
        </header>
        <div className={styles.log}>
          {log.map((entry, i) => (
            <div key={i} className={styles.logLine}>
              <span className={styles.logTime}>[{entry.time}]</span>{" "}
              <span
                className={`${styles.logTag} ${
                  entry.tone === "primary" ? styles.logTagPrimary : styles.logTagSecondary
                }`}
              >
                {entry.tag}
              </span>{" "}
              <span className={styles.logMsg}>{entry.message}</span>
            </div>
          ))}
        </div>
      </div>
      <footer className={styles.foot}>
        <span className={`${styles.footMeta} font-label-sm`}>
          下次全局巡检周期: <span className={`${styles.footTimer} font-code`}>{mm}:{ss}</span>
        </span>
        <span className={`${styles.footQueue} font-code`}>集群队列: 空闲</span>
      </footer>
    </article>
  );
}

/* (Unused symbol retained only to keep import surface stable in case future
    iterations add an agent action footer button.) */
function _importedIconSpanIsUsed() {
  return <IconSpan name="smart_toy" size={14} />;
}
