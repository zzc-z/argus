'use client'

import * as React from 'react'
import { useRouter } from 'next/navigation'
import { IconSpan } from '@/components/common/IconSpan'
import { KbdHint } from '@/components/common/KbdHint'
import styles from './index.module.css'

export interface ActionGroupProps {
  /** Optional click handler invoked when the user clicks "返回研究看板". */
  onBackToDashboard?: () => void
}

/**
 * 两个真实可用的出口。
 *
 * ## 原来这里有三颗按钮，其中两颗是假的
 *
 * - 「全局检索研究课题 ⌘K」—— 404 页上没有任何课题可检索，后端也没有
 *   检索接口；按下去只是弹一个 `window.alert`。
 * - 「重新调度执行智能体」—— 假装在重调度：转 1.8 秒圈后提示「重调度
 *   完成」再刷新页面。404 是路由没匹配上，**没有智能体可调度**；这个
 *   动画在骗人。
 *
 * 只留「返回研究看板」（真实跳转）与「回到首页」。
 */
export function ActionGroup({ onBackToDashboard }: ActionGroupProps) {
  const router = useRouter()

  const goDashboard = React.useCallback(() => {
    if (onBackToDashboard) {
      onBackToDashboard()
      return
    }
    router.push('/dashboard')
  }, [onBackToDashboard, router])

  return (
    <div className={styles.group}>
      <button
        type="button"
        onClick={goDashboard}
        className={`${styles.btn} ${styles.primary}`}
      >
        <IconSpan name="space_dashboard" size={18} />
        <span className="font-headline-sm">返回研究看板</span>
        <KbdHint tone="dark" className={styles.kbdOnDark}>
          ⌘H
        </KbdHint>
      </button>

      <button
        type="button"
        onClick={() => router.push('/explore')}
        className={`${styles.btn} ${styles.secondary}`}
      >
        <IconSpan name="travel_explore" size={18} />
        <span className="font-headline-sm">开始一次新的研究</span>
      </button>
    </div>
  )
}
