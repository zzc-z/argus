'use client'

import * as React from 'react'
import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { IconSpan } from '@/components/common/IconSpan'
import { cn } from '@/lib/utils'
import styles from './index.module.css'

export interface ResearchDockProps {
  /** 报告标题。用作「针对这篇报告继续问」的上下文。 */
  question: string
}

const DOCK_PLACEHOLDER = '针对本篇研报继续提问...'

/**
 * 底部「继续提问」浮条。
 *
 * ## 为什么提交是「带上下文跳到 explore」而不是直接开流
 *
 * 报告页的正文是**已落盘的历史**。继续提问是一次**新的研究**——它要跑
 * 完整的 agent 循环、要重新检索、要新的 SSE 流。explore 页已经把这套
 * 跑通了（含 DAG 推进、引用角标、忠实度校验），在报告页再实现一遍是重复。
 *
 * 所以这里把问题带上下文跳到 explore：`/explore?question=<原文>`。
 * explore 页读这个 query 参数预填输入框——**不自动提交**。用户看到自己
 * 填的内容、可以改，再按发送。自动提交等于替他花掉一次真金白银的模型调用。
 */
export function ResearchDock({ question }: ResearchDockProps) {
  const [draft, setDraft] = useState('')
  const router = useRouter()

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = draft.trim()
    if (!trimmed) return
    // 把原问题作为上下文带过去，用户在前面续写。
    const next = `${question}\n\n追问：${trimmed}`
    router.push(`/explore?question=${encodeURIComponent(next)}`)
  }

  return (
    <div className={styles.dock}>
      <form className={styles.bar} onSubmit={handleSubmit}>
        <div className={styles.avatar}>
          <IconSpan name="smart_toy" size={18} />
        </div>
        <input
          className={cn(styles.input, 'font-body-sm')}
          type="text"
          placeholder={DOCK_PLACEHOLDER}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          aria-label="针对本篇研报提问"
        />
        <div className={styles.toolbar}>
          <button type="submit" className={cn(styles.submitBtn, 'font-headline-sm')}>
            <span>继续推演</span>
            <IconSpan name="arrow_upward" size={16} />
          </button>
        </div>
      </form>
    </div>
  )
}
