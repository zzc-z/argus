'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import { SESSION_BREADCRUMB, MODEL_BADGE } from '../../mock'
import styles from './index.module.css'

export interface TopBarProps {
  onToggleInspector: () => void
  inspectorOpen: boolean
}

/**
 * 56px sticky top bar — Argus wordmark + session breadcrumb, ⌘K search,
 * live token counter, inspector toggle, user avatar.
 *
 * Color literals are hard-coded because argus_2 has its own dark surface
 * palette independent of the 47 token system.
 */
export function TopBar({ onToggleInspector, inspectorOpen }: TopBarProps) {
  return (
    <header className={styles.bar}>
      {/* Left: brand + breadcrumb + model badge */}
      <div className={styles.left}>
        <div className={styles.brand}>
          <div className={styles.mark}>
            <IconSpan name="target" size={14} className={styles.markIcon} />
          </div>
          <span className={styles.brandWord}>argus</span>
        </div>
        <span className={styles.sep}>/</span>
        <span className={styles.session}>{SESSION_BREADCRUMB}</span>
        <span className={styles.modelBadge}>{MODEL_BADGE}</span>
      </div>

      {/* Center: search */}
      <div className={styles.search}>
        <div className={styles.searchWrap}>
          <IconSpan name="search" size={14} className={styles.searchIcon} />
          <input
            type="text"
            placeholder="跳转至 Agent 追踪、数据源或会话 (⌘K)"
            className={styles.searchInput}
          />
          <div className={styles.searchKbd}>
            <kbd className={styles.kbd}>⌘K</kbd>
          </div>
        </div>
      </div>

      {/* Right: live status + toggle + avatar */}
      <div className={styles.right}>
        <div className={styles.live}>
          <span className={styles.liveDot} />
          <span className={styles.liveText}>流式传输中 · 8.2k tokens</span>
        </div>

        <button
          type="button"
          onClick={onToggleInspector}
          className={`${styles.toggle} ${inspectorOpen ? styles.toggleOpen : ''}`}
          title="打开/收起检查器"
        >
          <IconSpan name="view_sidebar" size={14} className={styles.toggleIcon} />
          <span className={styles.toggleLabel}>检查器</span>
        </button>

        <div className={styles.avatar} title="账户">
          TL
        </div>
      </div>
    </header>
  )
}
