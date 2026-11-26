'use client'

import * as React from 'react'

import { IconSpan } from '@/components/common/IconSpan'

import styles from './index.module.css'

export type ToastTone = 'success' | 'info' | 'error'

export interface ToastProps {
  /** 提示文案。为 null 时不显示卡片（live region 仍在）。 */
  message: string | null
  /**
   * 提示的性质。
   *
   * - `success` / `info` —— 常规通知，走 `role="status"`（礼貌播报）
   * - `error` —— 出错了，走 `role="alert"`（打断当前播报）
   */
  tone?: ToastTone
  /** 自动消失的延时（毫秒）。 */
  duration?: number
  /** 到点时调用——父组件据此把 message 清成 null。 */
  onDismiss?: () => void
}

/**
 * 顶部居中的浮层提示。
 *
 * ## 为什么 live region 常驻
 *
 * `role="status"` 的区域如果和文案**同时挂载**，部分读屏软件不会播报
 * ——live region 必须在内容变化**之前**就存在。所以这个组件永远渲染
 * 那两个区域，只把卡片按 message 的有无挂进挂出。
 *
 * ## 为什么分成两个 live region
 *
 * `role="status"` 是礼貌播报（等当前内容念完），`role="alert"` 是打断
 * 播报。错误提示用后者才对——但**同一个元素上动态改 role** 是屏幕
 * 阅读器不推荐的（它可能只认挂载时的那次 role）。所以两个区域各挂
 * 一次，错误文案进 alert 那个，成功文案进 status 那个。
 *
 * ## 为什么不自己管「消失」
 *
 * 组件只在到点时通知父组件（onDismiss），由父组件把 message 清成
 * null。组件内部若自己 setState 清文案，就得在 effect 里同步 state
 * （React 的 set-state-in-effect 规则会报），而且父组件的 message
 * 还在、卡片却已经没了——两份状态会分家。
 *
 * ## 为什么倒计时不依赖 onDismiss 的引用
 *
 * 父组件多半传的是内联箭头函数，每次渲染都是新引用。若倒计时依赖它，
 * 每次渲染都会重置计时器，提示永远不消失。所以回调走 ref。
 */
export function Toast({ message, tone = 'success', duration = 3000, onDismiss }: ToastProps) {
  const dismissRef = React.useRef(onDismiss)
  React.useEffect(() => {
    dismissRef.current = onDismiss
  })

  React.useEffect(() => {
    if (!message) return
    const timer = window.setTimeout(() => dismissRef.current?.(), duration)
    return () => window.clearTimeout(timer)
  }, [message, duration])

  const isError = tone === 'error'
  const icon = isError ? 'error' : tone === 'info' ? 'info' : 'check_circle'

  return (
    <div className={styles.viewport}>
      <div role="status" aria-live="polite" aria-atomic="true">
        {message && !isError ? (
          <div className={styles.card}>
            <span className={styles.icon}>
              <IconSpan name={icon} size={18} />
            </span>
            <span className={styles.text}>{message}</span>
          </div>
        ) : null}
      </div>
      <div role="alert" aria-atomic="true">
        {message && isError ? (
          <div className={styles.card}>
            <span className={styles.iconError}>
              <IconSpan name={icon} size={18} />
            </span>
            <span className={styles.text}>{message}</span>
          </div>
        ) : null}
      </div>
    </div>
  )
}
