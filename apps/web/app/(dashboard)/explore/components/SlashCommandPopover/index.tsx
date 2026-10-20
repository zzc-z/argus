'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import type { SlashCommand } from '../../constants'
import styles from './index.module.css'

export interface SlashCommandPopoverProps {
  visible: boolean
  commands: SlashCommand[]
  /** 当前高亮行；-1 表示没有高亮。方向键 / Tab 移动它。 */
  activeIndex: number
  onSelect: (cmd: SlashCommand) => void
}

/**
 * Slash command popover shown above the prompt input when the user types "/".
 *
 * 选中不是「执行指令」而是把 `template` 填进输入框——后端不认斜杠指令，
 * 真正发出去的必须是展开后的中文问题（见 constants.ts 的 SlashCommand）。
 */
export function SlashCommandPopover({
  visible,
  commands,
  activeIndex,
  onSelect,
}: SlashCommandPopoverProps) {
  if (!visible) return null

  return (
    <div className={styles.popover} role="listbox">
      <div className={styles.head}>
        <IconSpan name="bolt" size={13} className={styles.headIcon} />
        <span>提问模板 (Prompt Templates)</span>
      </div>
      {commands.map((c, i) => (
        <button
          key={c.cmd}
          type="button"
          role="option"
          aria-selected={i === activeIndex}
          className={`${styles.row} ${i === activeIndex ? styles.rowActive : ''}`}
          onClick={() => onSelect(c)}
          onMouseEnter={() => undefined}
        >
          <div className={styles.rowLeft}>
            <span className={styles.rowCmd}>{c.cmd}</span>
            <span className={styles.rowDesc}>{c.description}</span>
          </div>
          <span className={styles.rowHint}>Tab</span>
        </button>
      ))}
    </div>
  )
}
