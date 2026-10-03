import * as React from 'react'
import type { HealthSnapshot, HealthSource } from '../../mock'
import styles from './index.module.css'

export interface HealthCardProps {
  health: HealthSnapshot
}

/**
 * Right-rail card — source ingestion health (3 source rows + bar + auto-recovery).
 * 1:1 extracted from argus_notifications/code.html lines 479-512.
 */
export function HealthCard({ health }: HealthCardProps) {
  return (
    <section className={styles.card}>
      <header className={styles.header}>
        <h3 className={styles.title}>信源心跳健康度</h3>
        <span className={styles.score}>{health.totalScoreLabel}</span>
      </header>

      <div className={styles.sources}>
        {health.sources.map((src) => (
          <SourceRow key={src.id} src={src} />
        ))}
      </div>

      <div className={styles.recovery}>
        <span className={styles.recoveryLabel}>
          自动恢复机制: {health.autoRecoveryEnabled ? 'ENABLED' : 'DISABLED'}
        </span>
        <button type="button" className={styles.recoveryBtn}>
          {health.recoveryButtonLabel}
        </button>
      </div>
    </section>
  )
}

function SourceRow({ src }: { src: HealthSource }) {
  const barClass = src.tone === 'ok' ? styles.barOk : styles.barWarn
  const valueClass = src.tone === 'ok' ? styles.valueOk : styles.valueWarn
  return (
    <>
      <div className={styles.sourceRow}>
        <span className={styles.sourceLabel}>{src.label}</span>
        <span className={valueClass}>{src.value}</span>
      </div>
      <div className={styles.bar}>
        <div
          className={`${styles.barFill} ${barClass}`}
          style={{ width: `${src.fillPercent}%` }}
        />
      </div>
    </>
  )
}
