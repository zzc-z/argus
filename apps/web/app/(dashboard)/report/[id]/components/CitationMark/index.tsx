'use client'

import * as React from 'react'
import { cn } from '@/lib/utils'
import styles from './index.module.css'

export interface CitationMarkProps {
  /** 角标编号，与正文里的 `[n]` 对应。 */
  n: number
  /**
   * 引用表里有没有这个编号。
   *
   * 没有时渲染成裸字符而不是按钮——正文里的 `[n]` 只是 prompt 里的软约束，
   * 模型会编造越界编号。给一个点了没反应的按钮会让用户以为页面坏了；
   * 裸字符反而让用户看出「这个号是模型自己编的」。
   */
  resolvable: boolean
  /** 点击回调，由父组件接到来源面板的定位逻辑。 */
  onClick?: () => void
  className?: string
}

/**
 * 正文里的行内引用角标。可解析时是可点的按钮，不可解析时是裸字符。
 */
export function CitationMark({ n, resolvable, onClick, className }: CitationMarkProps) {
  if (!resolvable) {
    return <span className={cn(styles.unresolved, 'font-code', className)}>[{n}]</span>
  }

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(styles.mark, 'font-code', className)}
      aria-label={`引用 ${n}`}
    >
      {n}
    </button>
  )
}
