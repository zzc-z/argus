'use client'

/**
 * 登录页的交互外壳。
 *
 * 为什么从 `page.tsx` 里拆出来：`page.tsx` 要导出 `metadata`（这一页的
 * 标题是「登录 | Argus」，不是根 layout 的默认值），而带 `metadata` 导出
 * 的文件必须是 server component。快捷键快捷键闪烁逻辑需要 useEffect，
 * 所以它住在这里，page.tsx 只负责渲染。
 *
 * 结构（左表单 / 右可视化）与设计稿一致，所有视觉样式在各子组件的
 * `index.module.css` 里。
 */

import * as React from 'react'
import { useEffect } from 'react'

import { LoginHeader } from '../LoginHeader'
import { LoginForm } from '../LoginForm'
import { TrustBadges } from '../TrustBadges'
import { RightPanel } from '../RightPanel'

import styles from '../../page.module.css'

export function LoginScreen() {
  // Keyboard shortcuts (⌘G / ⌘W) → flash OAuth buttons.
  // 焦点在输入框里时不响应，否则打字会闪按钮。
  useEffect(() => {
    const flash = (id: string) => {
      const btn = document.getElementById(id)
      if (!btn) return
      btn.classList.add('ring-2', 'ring-purple-400', 'scale-[0.98]')
      window.setTimeout(() => {
        btn.classList.remove('ring-2', 'ring-purple-400', 'scale-[0.98]')
      }, 200)
    }

    const handler = (e: KeyboardEvent) => {
      const tag = (document.activeElement as HTMLElement | null)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA') return
      if (e.key === 'g' || e.key === 'G') flash('btn-oauth-github')
      else if (e.key === 'w' || e.key === 'W') flash('btn-oauth-google')
    }

    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [])

  return (
    <main className={styles.main}>
      {/* 左栏：认证区 */}
      <section className={styles.left}>
        <LoginHeader />
        <LoginForm />
        <Legal />
        <TrustBadges />
      </section>

      {/* 右栏：科技感可视化 */}
      <RightPanel />
    </main>
  )
}

/** 服务条款/隐私政策那行小字。没有自己的样式，也不再复用，留在原地。 */
function Legal() {
  return (
    <p className={styles.legal}>
      继续操作即表示您已阅读并同意 Argus 的
      <a className={styles.legalLink} href="#">
        《服务条款》
      </a>
      与
      <a className={styles.legalLink} href="#">
        《隐私政策与数据隔离承诺》
      </a>
    </p>
  )
}
