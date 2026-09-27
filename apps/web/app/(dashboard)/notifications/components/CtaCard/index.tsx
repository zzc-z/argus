import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import styles from './index.module.css'

/**
 * Right-rail purple gradient CTA — "configure agent DAG".
 * 1:1 extracted from argus_notifications/code.html lines 513-531.
 */
export function CtaCard() {
  return (
    <section className={styles.card}>
      <div className={styles.body}>
        <div className={styles.eyebrow}>
          <IconSpan name="auto_awesome" size={16} />
          <span>Argus 智能体集群</span>
        </div>
        <h4 className={styles.heading}>需要按周自动汇总生成研报?</h4>
        <p className={styles.copy}>配置多智能体合成工作流,将通知动态直接串联至深度综述生成引擎。</p>
        <button type="button" className={styles.cta}>
          立即配置智能体 DAG
        </button>
      </div>
      {/* Decorative ambient SVG watermark (kept inline per AGENTS.md §16.7 — no SVG-utility components). */}
      <svg
        className={styles.watermark}
        fill="currentColor"
        viewBox="0 0 100 100"
        aria-hidden="true"
      >
        <circle cx="50" cy="50" fill="none" r="40" stroke="currentColor" strokeWidth="4" />
        <path d="M50 20 L50 80 M20 50 L80 50" stroke="currentColor" strokeWidth="4" />
      </svg>
    </section>
  )
}
