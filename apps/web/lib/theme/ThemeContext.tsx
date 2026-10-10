'use client'

import * as React from 'react'
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

export type Theme = 'light' | 'dark'

const STORAGE_KEY = 'tourl-theme'

interface ThemeContextValue {
  theme: Theme
  setTheme: (next: Theme) => void
  toggle: () => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

function readStoredTheme(): Theme | null {
  if (typeof window === 'undefined') return null
  const stored = window.localStorage.getItem(STORAGE_KEY)
  return stored === 'dark' || stored === 'light' ? stored : null
}

/**
 * Theme provider for the `/report` page subtree.
 *
 * Writes `data-theme="light|dark"` on the closest element this provider wraps
 * (caller is responsible for binding the attribute). CSS variables / class
 * overrides live in `report/page.module.css` under `[data-theme="dark"]` so
 * the dark palette only affects the report subtree — never bleeds out to the
 * dashboard chrome.
 *
 * SSR safe: server renders `light`; mount reads localStorage and syncs the DOM.
 */
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<Theme>('light')

  useEffect(() => {
    const stored = readStoredTheme()
    if (stored && stored !== theme) {
    // eslint-disable-next-line react-hooks/set-state-in-effect
      setThemeState(stored)
    }
    // 同 ThemeToggle：主题初值在 localStorage，SSR 阶段读不到，
    // 首次渲染只能用默认值，挂载后再同步。彻底修法是把主题存进 cookie
    // 并在服务端读取（layout 读 cookies() 决定初始 theme），
    // 那样这个 effect 可以整个删掉——属架构改动，单独排期。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next)
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(STORAGE_KEY, next)
    }
  }, [])

  const toggle = useCallback(() => {
    setThemeState((current) => {
      const next: Theme = current === 'light' ? 'dark' : 'light'
      if (typeof window !== 'undefined') {
        window.localStorage.setItem(STORAGE_KEY, next)
      }
      return next
    })
  }, [])

  const value = useMemo<ThemeContextValue>(() => ({ theme, setTheme, toggle }), [theme, setTheme, toggle])

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

/** Read theme + toggle. Throws if used outside `<ThemeProvider>`. */
export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) {
    throw new Error('useTheme must be used within a <ThemeProvider>')
  }
  return ctx
}