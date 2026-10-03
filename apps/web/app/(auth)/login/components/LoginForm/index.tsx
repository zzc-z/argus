'use client'

import * as React from 'react'
import { OAuthButton } from '../OAuthButton'
import { EmailInput } from '../EmailInput'
import { SsoPanel } from '../SsoPanel'
import { Separator } from '@/components/ui'
import styles from './index.module.css'

/**
 * Center vertical column — welcome typography, OAuth row, divider, email form.
 * Pure presentation; page.tsx owns keyboard shortcuts.
 */
export function LoginForm() {
  return (
    <div className={styles.root}>
      <div className={styles.welcome}>
        <h1
          className={`${styles.title} font-headline-lg font-semibold tracking-tight`}
        >
          登录您的研究工作台
        </h1>
        <p className={`${styles.subtitle} font-body-sm text-secondary leading-relaxed`}>
          多智能体深度研报 · 面向工程师与研究员的 AI 洞察引擎
        </p>
      </div>

      <div className={styles.oauth}>
        <OAuthButton provider="github" label="使用 GitHub 账号继续" shortcut="⌘G" tone="dark" />
        <OAuthButton
          provider="google"
          label="使用 Google Workspace 账号继续"
          shortcut="⌘W"
          tone="light"
        />
      </div>

      <div className={styles.divider}>
        <Separator className={styles.dividerLine} />
        <span className={`${styles.dividerLabel} font-label-sm uppercase tracking-wider`}>
          或通过企业邮箱 / SSO
        </span>
      </div>

      <form className={styles.form} onSubmit={(e) => e.preventDefault()}>
        <EmailInput id="work-email" label="工作邮箱地址" placeholder="name@company.com" />
        <SsoPanel />
      </form>
    </div>
  )
}
