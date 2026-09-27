/**
 * KpiCard — 1:1 with argus_dashboard/code.html KPI tile.
 *
 * Card anatomy:
 *   - head row:  uppercase label (left) + decorative icon (right)
 *   - value row: large numeric + font-code sub (e.g. "/ 8 最大配额")
 *   - footer row: tone-coloured dot/icon + prefix + bold highlight + suffix
 *   - bottom:    absolute 2px progress strip (full card width)
 *
 * Card root is position: relative + overflow: hidden so the progress strip
 * pins to the bottom edge of the card.
 */

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import type { Kpi } from '../../mock'
import styles from './index.module.css'

export interface KpiCardProps {
  kpi: Kpi
}

export function KpiCard({ kpi }: KpiCardProps) {
  const isDotFooter =
    kpi.footerIconTone === 'success' && kpi.footerIcon === 'bolt'
      ? false
      : kpi.footerIconTone === 'success' && kpi.footerIcon === 'arrow_upward'
        ? false
        : kpi.footerIcon === 'bolt'
          ? false
          : false

  return (
    <div className={styles.root}>
      <div className={styles.head}>
        <span className={`${styles.label} text-label-sm font-label-sm uppercase tracking-wider`}>
          {kpi.label}
        </span>
        <IconSpan name={kpi.icon} size={18} className={styles.headIcon} />
      </div>

      <div className={styles.valueRow}>
        <span
          className={`${styles.value} font-headline-xl text-headline-xl text-on-surface font-semibold tracking-tight`}
        >
          {kpi.value}
        </span>
        <span className={`${styles.sub} text-code font-code text-secondary`}>{kpi.sub}</span>
      </div>

      <div className={styles.footer}>
        {isDotFooter ? null : kpi.footerIcon === 'bolt' ? (
          <span className={styles.footerDot} aria-hidden="true" />
        ) : kpi.footerIcon === 'arrow_upward' ? (
          <IconSpan name={kpi.footerIcon} size={16} className={styles.footerIconSuccess} />
        ) : kpi.footerIcon === 'verified' ? (
          <IconSpan name={kpi.footerIcon} size={16} className={styles.footerIconPrimary} />
        ) : (
          <IconSpan name={kpi.footerIcon} size={16} className={styles.footerIconSecondary} />
        )}
        <span className={`${styles.footerText} text-body-sm font-body-sm`}>
          {kpi.footerPrefix}
          <strong className={`${styles.footerHighlight} text-on-surface font-medium`}>
            {kpi.footerHighlight}
          </strong>
          {kpi.footerSuffix}
        </span>
      </div>

      <div className={styles.progressTrack} aria-hidden="true">
        <div className={styles.progressFill} style={{ width: `${kpi.progress}%` }} />
      </div>
    </div>
  )
}
