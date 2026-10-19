'use client'

import * as React from 'react'
import { Suspense } from 'react'
import { useSearchParams } from 'next/navigation'
import { OAuthButton } from '../OAuthButton'
import { EmailInput } from '../EmailInput'
import { SsoPanel } from '../SsoPanel'
import { Separator } from '@/components/ui'
import { useUser } from '@/lib/auth'
import styles from './index.module.css'

/**
 * OAuth 回调失败时后端带的 error 参数 → 用户能看懂的一句话。
 *
 * 键名来自后端 `_bounce_to_login`（只放行字母数字下划线），
 * 但前端不直接展示原值——未知键统一落到「登录未完成」，
 * 避免后端将来加新错误码时前端显示 undefined。
 */
const ERROR_MESSAGES: Record<string, string> = {
  access_denied: '你取消了 GitHub 授权，可以重新发起登录。',
  provider_unavailable: '暂时连不上 GitHub，请稍后重试。',
  provider_rejected: 'GitHub 拒绝了这次登录，请重新发起。',
}

/**
 * 提示条。单独拆出来是因为它用了 useSearchParams——
 * Next 16 要求任何读 URL 的 Client Component 都必须在 <Suspense> 边界内，
 * 否则整条路由无法静态预渲染，构建时报 blocking-prerender。
 */
function LoginErrorBanner() {
  const params = useSearchParams()
  const code = params.get('error')
  if (!code) return null

  return (
    <p
      role="alert"
      className="w-full rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-[13px] leading-relaxed text-red-300"
    >
      {ERROR_MESSAGES[code] ?? '登录未完成，请重试。'}
    </p>
  )
}

/**
 * OAuth 按钮。单独拆出来是因为它要读 `?next=`（useSearchParams）——
 * Next 16 要求任何读 URL 的 Client Component 都在 <Suspense> 边界内。
 *
 * `next` 透传给后端：用户在「因为登录态被清空而被踢到 /login」的情况下
 * 点 GitHub，登录完仍回到原来那页，而不是又被弹回 /dashboard。
 */
function GithubOAuthButton() {
  const { loginWithGithub } = useUser()
  const next = useSearchParams().get('next')

  return (
    <OAuthButton
      provider="github"
      label="使用 GitHub 账号继续"
      shortcut="⌘G"
      tone="dark"
      onClick={() => loginWithGithub(next ?? undefined)}
    />
  )
}

export function LoginForm() {
  return (
    <div className={styles.root}>
      <Suspense fallback={null}>
        <LoginErrorBanner />
      </Suspense>

      <div className={styles.welcome}>
        <h1 className={`${styles.title} font-headline-lg font-semibold tracking-tight`}>
          登录您的研究工作台
        </h1>
        <p className={`${styles.subtitle} font-body-sm text-secondary leading-relaxed`}>
          多智能体深度研报 · 面向工程师与研究员的 AI 洞察引擎
        </p>
      </div>

      <div className={styles.oauth}>
        <Suspense fallback={null}>
          <GithubOAuthButton />
        </Suspense>
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
