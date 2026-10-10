'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import {
  SIDEBAR_CLUSTER_BAR_WIDTH,
  SIDEBAR_CLUSTER_DAG,
  SIDEBAR_CLUSTER_LATENCY,
  SIDEBAR_CLUSTER_STATUS,
  SIDEBAR_CLUSTER_TITLE,
  SIDEBAR_NAV,
  SIDEBAR_NAV_LABEL,
  SIDEBAR_SESSION_LABEL,
  SIDEBAR_VERSION,
  SIDEBAR_WORKSPACE_LABEL,
} from '../../mock'
import styles from './index.module.css'

/**
 * Left navigation rail. 1:1 with argus_reports/code.html.
 * Pure presentation; page.tsx owns any active-state interactivity.
 */
export function Sidebar() {
  return (
    <aside className={styles.root}>
      <div className={styles.top}>
        {/* Brand block */}
        <div className={styles.brandRow}>
          <div className={styles.brand}>
            <div className={styles.brandIcon}>
              <IconSpan name="visibility" size={20} />
            </div>
            <div className={styles.brandText}>
              <span className={styles.brandName}>Argus</span>
              <span className={styles.brandSub}>Synthesizer Core</span>
            </div>
          </div>
          <span className={styles.version}>{SIDEBAR_VERSION}</span>
        </div>

        {/* Workspace selector */}
        <div className={styles.workspaceWrap}>
          <button type="button" className={styles.workspace}>
            <div className={styles.workspaceLeft}>
              <IconSpan name="layers" size={18} className={styles.workspaceIcon} />
              <span className={styles.workspaceLabel}>{SIDEBAR_WORKSPACE_LABEL}</span>
            </div>
            <IconSpan name="unfold_more" size={16} className={styles.workspaceIcon} />
          </button>
        </div>

        <div className={styles.divider} />

        {/* Nav */}
        <div className={styles.navWrap}>
          <span className={styles.navLabel}>{SIDEBAR_NAV_LABEL}</span>
          <nav className={styles.nav}>
            {SIDEBAR_NAV.map((item) => (
              <a
                key={item.id}
                href={item.href}
                className={`${styles.navItem} ${item.active ? styles.navItemActive : ''}`}
                aria-current={item.active ? 'page' : undefined}
              >
                <IconSpan name={item.icon} size={18} />
                <span>{item.label}</span>
              </a>
            ))}
          </nav>
        </div>
      </div>

      {/* Bottom cluster + session */}
      <div className={styles.bottom}>
        <div className={styles.cluster}>
          <div className={styles.clusterRow}>
            <span className={styles.clusterTitle}>{SIDEBAR_CLUSTER_TITLE}</span>
            <span className={styles.clusterStatus}>{SIDEBAR_CLUSTER_STATUS}</span>
          </div>
          <div className={styles.clusterBar}>
            <div className={styles.clusterBarFill} style={{ width: SIDEBAR_CLUSTER_BAR_WIDTH }} />
          </div>
          <div className={styles.clusterMeta}>
            <span>{SIDEBAR_CLUSTER_DAG}</span>
            <span>{SIDEBAR_CLUSTER_LATENCY}</span>
          </div>
        </div>

        <div className={styles.session}>
          <span>{SIDEBAR_SESSION_LABEL}</span>
          <IconSpan name="terminal" size={16} className={styles.sessionIcon} />
        </div>
      </div>
    </aside>
  )
}
