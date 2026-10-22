'use client'

import * as React from 'react'
import { cn } from '@/lib/utils'
import { IconSpan } from '@/components/common/IconSpan'
import { settingsNavItems, type SettingsNavId, type VectorIndexDiagnostic } from '../../view'
import styles from './index.module.css'

export interface SettingsSidebarProps {
  activeId: SettingsNavId
  onSelect: (id: SettingsNavId) => void
  /** 向量索引诊断。null = 还没加载出来。 */
  diagnostic: VectorIndexDiagnostic | null
}

/**
 * Left settings navigation (design §19-80).
 * Each item is a button (not an <a>) — selection is client-side state.
 * Mini diagnostics card below the nav lists vector index health.
 *
 * 诊断数据来自 `GET /api/v1/settings/status`（映射见 `view.ts`）。
 */
export function SettingsSidebar({ activeId, onSelect, diagnostic }: SettingsSidebarProps) {
  const used = diagnostic?.used ?? 0
  const total = diagnostic?.total ?? 0
  // 比例可能大于 1（后端统计的是全库向量数，切片数是当前用户的），
  // 进度条宽度封顶在 100%，免得溢出轨道。
  const pct = Math.min(100, Math.round((diagnostic?.ratio ?? 0) * 100))

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
                {item.hint}
              </span>
            </button>
          )
        })}
      </div>

      <div className={styles.divider} aria-hidden="true" />

      <div className={styles.diag}>
        <div className={styles.diagHead}>
          <span className={cn(styles.diagLabel, 'font-label-sm')}>
            {diagnostic?.label ?? '向量索引状态'}
          </span>
          <span className={cn(styles.diagStatus, 'font-code text-primary')}>
            {diagnostic?.statusLabel ?? '加载中'}
          </span>
        </div>
        <div className={styles.barTrack}>
          <div className={styles.barFill} style={{ width: `${pct}%` }} />
        </div>
        <div className={cn(styles.diagFoot, 'font-code text-secondary')}>
          <span>
            {used} / {total} 切片
          </span>
          <span>{pct}%</span>
        </div>
      </div>
    </nav>
  )
}
