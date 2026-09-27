'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import { KbdHint } from '@/components/common/KbdHint'
import { SlashCommandPopover } from '../SlashCommandPopover'
import type { SlashCommand } from '../../mock'
import styles from './index.module.css'

export interface PromptInputProps {
  value: string
  onChange: (next: string) => void
  onSubmit: (value: string) => void
  slashVisible: boolean
  onSlashSelect: (cmd: SlashCommand) => void
}

/**
 * 48px single-line prompt input with:
 *   - Left swap-vertical toggle glyph
 *   - Slash command popover (parent-driven visibility)
 *   - ⌘+↵ shortcut hint
 *   - Submit button
 */
export function PromptInput({
  value,
  onChange,
  onSubmit,
  slashVisible,
  onSlashSelect,
}: PromptInputProps) {
  const inputRef = React.useRef<HTMLInputElement | null>(null)

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Escape') {
      // Always hide popover on Escape.
      if (slashVisible) onChange('')
    }
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault()
      const trimmed = value.trim()
      if (trimmed) onSubmit(trimmed)
    }
  }

  const handleSend = () => {
    const trimmed = value.trim()
    if (!trimmed) return
    onSubmit(trimmed)
  }

  return (
    <div className={styles.wrap}>
      <SlashCommandPopover visible={slashVisible} onSelect={onSlashSelect} />

      <div className={styles.bar}>
        <span className={styles.toggleIcon}>
          <IconSpan name="swap_vert" size={16} />
        </span>
        <input
          ref={inputRef}
          type="text"
          className={styles.input}
          placeholder="输入任何问题... (键入 '/' 获取指令)"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
        />
        <div className={styles.rightCluster}>
          <div className={styles.shortcut}>
            <KbdHint tone="light">⌘+↵ 发送</KbdHint>
          </div>
          <button type="button" className={styles.sendBtn} onClick={handleSend}>
            <span>发送</span>
            <IconSpan name="arrow_forward" size={13} />
          </button>
        </div>
      </div>
    </div>
  )
}
