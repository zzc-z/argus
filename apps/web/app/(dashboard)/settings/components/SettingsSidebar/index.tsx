'use client'

import * as React from 'react'
import { cn } from '@/lib/utils'
import { IconSpan } from '@/components/common/IconSpan'
import { settingsNavItems, vectorIndexDiagnostic, type SettingsNavId } from '../../mock'
import styles from './index.module.css'

export interface SettingsSidebarProps {
  activeId: SettingsNavId
  onSelect: (id: SettingsNavId) => void
}

/**
 * Left settings navigation (design §19-80).
 * Each item is a button (not an <a>) — selection is client-side state.
 * Mini diagnostics card below the nav lists vector index health.
 */
export function SettingsSidebar({ activeId, onSelect }: SettingsSidebarProps) {
  const { used, total, ratio } = vectorIndexDiagnostic
  const pct = Math.round(ratio * 100)

  return (
    <nav className={styles.nav} aria-label="设置导航">
      <div className={styles.heading}>配置分组 · Category</div>

      <div className={styles.list}>
        {settingsNavItems.map((item) => {
          const isActive = item.id === activeId
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => onSelect(item.id)}
              className={cn(
                styles.item,
                isActive && !item.danger && styles.itemActive,
                isActive && item.danger && styles.itemDangerActive,
                item.danger && !isActive && styles.itemDanger,
              )}
            >
              <IconSpan
                name={item.icon}
                size={18}
                className={isActive && !item.danger ? 'text-on-primary' : undefined}
              />
              <span className={cn(styles.label, 'font-body-sm')}>{item.label}</span>
              <span
                className={cn(
                  styles.hint,
                  'font-label-sm',
                  isActive && !item.danger && styles.hintActive,
                  isActive && item.danger && styles.hintDangerActive,
                  item.danger && !isActive && styles.hintDanger,
                )}
              >
                {isActive && item.id === 'memory' ? 'Active' : item.hint}
              </span>
            </button>
          )
        })}
      </div>

      <div className={styles.divider} aria-hidden="true" />

      <div className={styles.diag}>
        <div className={styles.diagHead}>
          <span className={cn(styles.diagLabel, 'font-label-sm')}>
            {vectorIndexDiagnostic.label}
          </span>
          <span className={cn(styles.diagStatus, 'font-code text-primary')}>
            {vectorIndexDiagnostic.statusLabel}
          </span>
        </div>
        <div className={styles.barTrack}>
          <div className={styles.barFill} style={{ width: `${pct}%` }} />
        </div>
        <div className={cn(styles.diagFoot, 'font-code text-secondary')}>
          <span>
            {used} / {total} 记忆项
          </span>
          <span>{pct}%</span>
        </div>
      </div>
    </nav>
  )
}
