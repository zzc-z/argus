'use client'

/**
 * Login page — composed from page-level components under ./components/.
 * All visual styling lives in each component's `index.module.less`.
 *
 * This page owns:
 *   - Keyboard shortcuts (⌘G / ⌘W) → flash OAuth buttons
 *   - Top-level layout grid (left form / right visualization)
 *
 * Page components used:
 *   - LoginHeader (top brand + utility)
 *   - LoginForm  (welcome + OAuth + email + SSO + legal)
 *   - TrustBadges (bottom-left three micro-badges)
 *   - RightPanel  (right column: ambient + DAG + testimonial)
 */

import * as React from 'react'
import { useEffect } from 'react'

import { LoginHeader } from './components/LoginHeader'
import { LoginForm } from './components/LoginForm'
import { TrustBadges } from './components/TrustBadges'
import { RightPanel } from './components/RightPanel'

import styles from './page.module.css'

export default function LoginPage() {
  // Keyboard shortcuts: ⌘G / ⌘W (or G/W) → flash OAuth button.
  // Skipped when focus is inside an input/textarea (verbatim from source).
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
      {/* LEFT COLUMN: Minimalist Precision Authentication Area (46%) */}
      <section className={styles.left}>
        <LoginHeader />
        <LoginForm />
        <Legal />
        <TrustBadges />
      </section>

      {/* RIGHT COLUMN: Immersive Tech Visualization */}
      <RightPanel />
    </main>
  )
}

/** Tiny inline sub-component for the legal terms paragraph.
 *  Kept inline because it has no styling of its own and isn't reused. */
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
