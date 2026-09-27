'use client'

import * as React from 'react'
import { ArgusMark } from '@/components/common/ArgusMark'
import { StatusDot } from '@/components/common/StatusDot'
import { IconSpan } from '@/components/common/IconSpan'
import styles from './index.module.css'

export interface ErrorHeaderProps {
  /** Cluster status text shown next to the live dot. */
  clusterStatus: string
}

/**
 * Top bar of the error page.
 * Left: Argus brand + version chip + tagline. Right: live cluster pill + back-to-workbench link.
 */
export function ErrorHeader({ clusterStatus }: ErrorHeaderProps) {
  return (
    <header className={styles.header}>
      <div className={styles.brand}>
        <div className={styles.brandMark}>
          <IconSpan name="hub" size={16} style={{ fontVariationSettings: "'FILL' 1" }} />
        </div>
        <div className={styles.brandText}>
          <div className={styles.brandRow}>
            <span
              className={`${styles.brandName} font-headline-sm text-on-surface font-semibold tracking-tight`}
            >
              Argus
            </span>
            <span className={`${styles.versionChip} font-label-sm`}>v2.4.1-rc3</span>
          </div>
          <span className={`${styles.brandTagline} font-label-sm text-secondary`}>
            Precision Intelligence Workspace
          </span>
        </div>
      </div>

      <div className={styles.right}>
        <div className={styles.statusPill}>
          <StatusDot color="purple" ping />
          <span className={`${styles.statusText} font-label-sm text-on-surface-variant`}>
            {clusterStatus}
          </span>
        </div>
        <a className={styles.backLink} href="#workbench">
          <IconSpan name="arrow_back" size={18} className="text-primary" />
          <span>返回工作台</span>
        </a>
      </div>
    </header>
  )
}

/** Re-export ArgusMark under a local alias to satisfy the brand-mark icon contract
 *  when the design needs a hub glyph instead of the brand mark. */
export function HubMark({ size = 20 }: { size?: number }) {
  return <ArgusMark size={size} aria-hidden="true" />
}
