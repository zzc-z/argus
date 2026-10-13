'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'

/** 研究工作台是全站唯一的主任务入口，两组快捷键都落到这里。 */
const RESEARCH_ROUTE = '/explore'

/**
 * ⌘K / ⌘N 全局快捷键 → 跳研究工作台。
 *
 * 为什么是独立 client 组件：`(dashboard)/layout.tsx` 是 server component，
 * 不能挂 useEffect。本组件只渲染 null，纯逻辑。
 *
 * ⌘K 挂在顶栏搜索框上——它暗示可搜索，但搜索面板是独立功能、不在本轮。
 * 与其让提示词骗人，不如给它一个真实且有用的落点：跳到唯一能发起研究的地方。
 */
export function QuickKeys() {
  const router = useRouter()

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      // ⌘K 在 Chrome/Edge 是「地址栏搜索」的系统保留键，浏览器自己会拦掉，
      // 页面上根本收不到这个事件。只在非 macOS 上（Ctrl+K）才有意义。
      if (!(e.metaKey || e.ctrlKey)) return
      const key = e.key.toLowerCase()
      if (key !== 'k' && key !== 'n') return
      e.preventDefault()
      router.push(RESEARCH_ROUTE)
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [router])

  return null
}