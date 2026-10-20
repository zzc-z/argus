'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import { KbdHint } from '@/components/common/KbdHint'
import { SlashCommandPopover } from '../SlashCommandPopover'
import type { SlashCommand } from '../../constants'
import styles from './index.module.css'

export interface PromptInputProps {
  value: string
  onChange: (next: string) => void
  onSubmit: (value: string) => void
  slashVisible: boolean
  slashCommands: SlashCommand[]
  onSlashSelect: (cmd: SlashCommand) => void
  /** 一轮研究在跑时禁止再提交。后端并发上限 4，再发就是 503。 */
  disabled?: boolean
}

/**
 * 48px single-line prompt input with:
 *   - Slash command popover (parent-driven visibility)
 *   - ⌘+↵ shortcut hint
 *   - Submit button
 */
export function PromptInput({
  value,
  onChange,
  onSubmit,
  slashVisible,
  slashCommands,
  onSlashSelect,
  disabled = false,
}: PromptInputProps) {
  const inputRef = React.useRef<HTMLInputElement | null>(null)
  // popover 里当前高亮的行。-1 = 没有高亮（还没按过方向键）。
  const [activeIndex, setActiveIndex] = React.useState(-1)

  const submit = () => {
    const trimmed = value.trim()
    if (!trimmed || disabled) return
    onSubmit(trimmed)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    // popover 打开时的键盘导航。
    //
    // 方向键移动高亮、Tab/Shift+Tab 在高亮行之间循环、Enter 选中。
    // 早期版本只有「Tab 选第一行」——弹层每一行都标着 Tab 提示，但 Tab
    // 永远落在第一行，且 Shift+Tab 被 preventDefault 吞掉（弹层按钮在 DOM
    // 里位于 input 之前，本来要靠 Shift+Tab 才能聚焦过去）。
    if (slashVisible && slashCommands.length > 0) {
      const last = slashCommands.length - 1
      if (e.key === 'ArrowDown' || (e.key === 'Tab' && !e.shiftKey)) {
        e.preventDefault()
        setActiveIndex((i) => (i + 1) % slashCommands.length)
        return
      }
      if (e.key === 'ArrowUp' || (e.key === 'Tab' && e.shiftKey)) {
        e.preventDefault()
        setActiveIndex((i) => (i <= 0 ? last : i - 1))
        return
      }
      if (e.key === 'Enter' && activeIndex >= 0) {
        e.preventDefault()
        const cmd = slashCommands[activeIndex]
        if (cmd) onSlashSelect(cmd)
        return
      }
    }
    if (e.key === 'Escape' && slashVisible) {
      onChange('')
      setActiveIndex(-1)
      return
    }
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault()
      submit()
    }
  }

  return (
    <div className={styles.wrap}>
      <SlashCommandPopover
        visible={slashVisible}
        commands={slashCommands}
        activeIndex={activeIndex}
        onSelect={onSlashSelect}
      />

      <div className={styles.bar}>
        <span className={styles.toggleIcon}>
          <IconSpan name="swap_vert" size={16} />
        </span>
        <input
          ref={inputRef}
          type="text"
          className={styles.input}
          placeholder={disabled ? '研究中…' : "输入任何问题... (键入 '/' 获取提问模板)"}
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
        />
        <div className={styles.rightCluster}>
          <div className={styles.shortcut}>
            <KbdHint tone="light">⌘+↵ 发送</KbdHint>
          </div>
          <button type="button" className={styles.sendBtn} onClick={submit} disabled={disabled}>
            <span>发送</span>
            <IconSpan name="arrow_forward" size={13} />
          </button>
        </div>
      </div>
    </div>
  )
}
