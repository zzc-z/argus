import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import type { Tone } from './tone'
import styles from './cells.module.css'

/** 单个按钮规格 */
export interface ActionBtn {
  /** 文字按钮文案（与 icon 二选一；都传则优先 icon） */
  label?: string
  /** 图标按钮的 Material icon name */
  icon?: string
  /** 仅图标按钮时，aria-label */
  ariaLabel?: string
  /** 颜色变体：默认主色紫；plain=灰；danger=红 */
  tone?: 'primary' | 'plain' | 'danger'
  /** 点击回调；不传则按钮 disabled */
  onClick?: () => void
}

export interface ActionsProps {
  /** 当前行的 tone（决定渲染哪一组按钮） */
  tone: Tone
  /** 按 tone 声明按钮组；tone 不在 keys 里时，整组渲染为空 */
  byTone: Partial<Record<Tone, ReadonlyArray<ActionBtn>>>
}

/**
 * Actions —— 按 tone 切换按钮组
 *  - tone 是数据驱动的；业务侧 columns.cell 直接 <Actions tone={row.status} byTone={...} />
 *  - 默认右对齐（justify-content: flex-end），适合操作列
 */
export function Actions({ tone, byTone }: ActionsProps) {
  const list = byTone[tone]
  if (!list || list.length === 0) {
    return <div className={styles.actions} aria-hidden="true" />
  }

  return (
    <div className={styles.actions}>
      {list.map((btn, i) => {
        const toneClass =
          btn.tone === 'danger'
            ? styles.actionBtnDanger
            : btn.tone === 'plain'
              ? styles.actionBtnPlain
              : ''
        if (btn.icon) {
          return (
            <button
              key={`${btn.icon}-${i}`}
              type="button"
              aria-label={btn.ariaLabel ?? btn.label}
              disabled={!btn.onClick}
              onClick={btn.onClick}
              className={styles.actionIconBtn}
            >
              <IconSpan name={btn.icon} size={18} />
            </button>
          )
        }
        return (
          <button
            key={`${btn.label ?? i}-${i}`}
            type="button"
            disabled={!btn.onClick}
            onClick={btn.onClick}
            className={`${styles.actionBtn} ${toneClass}`}
          >
            {btn.label}
          </button>
        )
      })}
    </div>
  )
}