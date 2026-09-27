'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import { StatusDot } from '@/components/common/StatusDot'
import type { ProviderStatus } from '../../mock'
import styles from './index.module.css'

export interface ProviderStatusSectionProps {
  providers: ProviderStatus[]
  onConfigure: () => void
}

/**
 * Quick Provider Status (design §425-495).
 * Compact grid of 4 active provider badges with ping/connection indicators.
 */
export function ProviderStatusSection({ providers, onConfigure }: ProviderStatusSectionProps) {
  return (
    <section className={styles.section}>
      <div className={styles.head}>
        <div className={styles.headLeft}>
          <IconSpan name="bolt" size={20} className="text-primary-container" />
          <h3 className={`${styles.title} font-headline-sm text-on-surface font-medium`}>
            模型与 API 接入简览
          </h3>
          <span className={`${styles.tag} font-label-sm text-secondary`}>
            Quick Provider Status
          </span>
        </div>
        <button type="button" className={styles.configure} onClick={onConfigure}>
          <span className={`${styles.configureLabel} font-label-sm text-primary`}>
            配置密钥与路由
          </span>
          <IconSpan name="chevron_right" size={14} className="text-primary" />
        </button>
      </div>

      <div className={styles.grid}>
        {providers.map((p) => (
          <div key={p.id} className={styles.card}>
            <div className={styles.cardHead}>
              <span className={`${styles.name} font-body-sm text-on-surface`}>{p.name}</span>
              <StatusDot color="emerald" ping={p.ping ?? false} />
            </div>
            <div className={styles.cardFoot}>
              <span className={`${styles.statusLabel} font-code text-secondary`}>
                {p.statusLabel}
              </span>
              <span
                className={`${styles.metricLabel} font-code ${
                  p.metricTone === 'primary' ? 'text-primary' : 'text-secondary'
                }`}
              >
                {p.metricLabel}
              </span>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
