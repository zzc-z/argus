'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import { METRIC_TILES } from '../../mock'
import styles from './index.module.css'

/**
 * 4-up KPI tile strip. Pure presentation; data from mock.ts.
 */
export function MetricStrip() {
  return (
    <section className={styles.root}>
      {METRIC_TILES.map((tile) => (
        <div key={tile.id} className={styles.tile}>
          <div className={styles.tileHeader}>
            <span className={styles.tileLabel}>{tile.label}</span>
            <IconSpan
              name={tile.icon}
              size={16}
              className={
                tile.valueTone === 'primary' ? styles.tileIconPrimary : styles.tileIconSuccess
              }
            />
          </div>
          <div className={styles.tileValueRow}>
            <span
              className={
                tile.valueTone === 'primary' ? styles.tileValuePrimary : styles.tileValueDefault
              }
            >
              {tile.value}
            </span>
            <span
              className={
                tile.subTone === 'success' ? styles.tileSubSuccess : styles.tileSubSecondary
              }
            >
              {tile.sub}
            </span>
          </div>
        </div>
      ))}
    </section>
  )
}
