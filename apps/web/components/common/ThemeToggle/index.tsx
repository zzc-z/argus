'use client'

import * as React from 'react'
import { useEffect, useState } from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import styles from './index.module.css'

type Theme = 'light' | 'dark'

const STORAGE_KEY = 'argus.theme'

/**
 * Light/Dark theme toggle button.
 *
 * - Reads `argus.theme` from localStorage on mount (default "light")
 * - Writes `data-theme="light|dark"` on `<html>` so CSS variables can switch
 * - On click, flips theme + persists to localStorage
 * - Uses Material Symbols `light_mode` / `dark_mode` via IconSpan (see §13)
 *
 * SSR safety: the icon is rendered with the *target* theme, not the current,
 * to keep server & client HTML identical before hydration.
 */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>('light')

  useEffect(() => {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    const initial: Theme = stored === 'dark' ? 'dark' : 'light'
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setTheme(initial)
    document.documentElement.dataset.theme = initial
    // set-state-in-effect 在这里是**必要**的，不是反模式：
    // 主题初值存在 localStorage（浏览器侧），服务端渲染时读不到，
    // 所以首次渲染只能先用默认值 'light'，挂载后再同步成真实值。
    // 真正的修法是让服务端也拿到这个值（cookie 持久化 + SSR 读 cookie），
    // 属于架构改动，见 AGENTS.md §16.8「React Compiler 一旦启用」同批排期。
  }, [])

  function toggle() {
    const next: Theme = theme === 'light' ? 'dark' : 'light'
    setTheme(next)
    document.documentElement.dataset.theme = next
    window.localStorage.setItem(STORAGE_KEY, next)
  }

  return (
    <button
      type="button"
      onClick={toggle}
      className={styles.toggle}
      aria-label={`切换到${theme === 'light' ? '深色' : '浅色'}主题`}
      title={`切换到${theme === 'light' ? '深色' : '浅色'}主题`}
    >
      <IconSpan name={theme === 'light' ? 'dark_mode' : 'light_mode'} size={16} />
    </button>
  )
}
