import * as React from "react";
import styles from "./index.module.css";

/**
 * Right-rail card — source ingestion health (3 source rows + bar + auto-recovery).
 * 1:1 extracted from argus_notifications/code.html lines 479-512.
 */
export function HealthCard() {
  return (
    <section className={styles.card}>
      <header className={styles.header}>
        <h3 className={styles.title}>信源心跳健康度</h3>
        <span className={styles.score}>99.8%</span>
      </header>

      <div className={styles.sources}>
        <SourceRow label="arXiv CS / AI 监听器" value="正常 (12/12)" tone="ok" fill="100%" />
        <SourceRow label="SEC Edgar 财务披露流" value="正常 (实时)" tone="ok" fill="100%" />
        <SourceRow label="行业科技博客 & 播客速记" value="1 个源异常" tone="warn" fill="80%" />
      </div>

      <div className={styles.recovery}>
        <span className={styles.recoveryLabel}>自动恢复机制: ENABLED</span>
        <button type="button" className={styles.recoveryBtn}>
          手动全量轮询
        </button>
      </div>
    </section>
  );
}

function SourceRow({
  label,
  value,
  tone,
  fill,
}: {
  label: string;
  value: string;
  tone: "ok" | "warn";
  fill: string;
}) {
  const barClass = tone === "ok" ? styles.barOk : styles.barWarn;
  const valueClass = tone === "ok" ? styles.valueOk : styles.valueWarn;
  return (
    <>
      <div className={styles.sourceRow}>
        <span className={styles.sourceLabel}>{label}</span>
        <span className={valueClass}>{value}</span>
      </div>
      <div className={styles.bar}>
        <div className={`${styles.barFill} ${barClass}`} style={{ width: fill }} />
      </div>
    </>
  );
}