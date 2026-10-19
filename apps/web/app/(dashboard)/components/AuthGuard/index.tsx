'use client'

import * as React from 'react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'

import { useUser } from '@/lib/auth'

/**
 * 登录守卫。包在 dashboard 的 chrome **外面**，只在没登录时介入。
 *
 * ## 为什么单独一个 client 子组件，而不是让整个 layout 变 client
 *
 * 守卫要读 `/me` 的运行期结果（cookie 是 HttpOnly，服务端拿不到），所以
 * 它自己必须是 client。把它做成子组件后，侧边栏、顶栏、它们的 CSS module
 * 仍然留在 server 侧渲染——client boundary 只有这一个文件。
 *
 * （Next 的 middleware 能读 cookie 并在 RSC 渲染前就 307，理论上更彻底，
 * 但本项目没有 middleware.ts；为一个守卫引入一层中间件不值当。）
 *
 * ## 三种状态，三种处理
 *
 * - `authenticated` → 渲染 children
 * - `anonymous`     → replace 到 /login，**带上当前路径**（见下）
 * - `unreachable`   → 显示「连不上」与重试按钮，**不跳登录页**
 * - `loading`       → 骨架，不是空白
 *
 * `unreachable` 这条是关键的：只有 401 能证明用户没登录。后端发版重启、
 * 网络抖动、500——这些都不是「你该去重新登录」，把它们当成未登录会让
 * 全站用户被踢去走一遍 OAuth，而他们的 session 明明还有效。
 *
 * ## 深链
 *
 * 把 `pathname + search` 作为 `?next=` 传给 /login，后端 OAuth callback
 * 登录完成后送回这里。用户把 `/sources` 分享给同事，对方登录完直接看到
 * 那一页，而不是被丢回 /dashboard 再自己找路。
 *
 * ## 为什么 replace 而非 push
 *
 * 登录态是回退历史里不该存在的一页。push 的话登出后按浏览器后退，会回到
 * 一个立刻又把他弹去 /login 的地址。
 */
/**
 * 导出组件只负责挂 Suspense 边界——`useSearchParams` 会让整条路由失去
 * 静态预渲染能力，没有边界 next build 会以 missing-suspense 失败。
 * 边界只包住 `Guard`（children 作为 prop 传下去，仍然正常预渲染）。
 */
export function AuthGuard({ children }: { children: React.ReactNode }) {
  return (
    <React.Suspense fallback={<FullPageSkeleton />}>
      <Guard>{children}</Guard>
    </React.Suspense>
  )
}

function Guard({ children }: { children: React.ReactNode }) {
  const { status, refresh } = useUser()
  const router = useRouter()
  const destination = useDestination()

  React.useEffect(() => {
    if (status === 'anonymous') {
      router.replace(`/login?next=${encodeURIComponent(destination)}`)
    }
  }, [status, destination, router])

  if (status === 'loading') return <FullPageSkeleton />
  if (status === 'unreachable') return <Unreachable onRetry={refresh} />
  if (status === 'anonymous') return <FullPageSkeleton />

  return <>{children}</>
}

/**
 * 用户原本要去的完整路径（含 query），用作登录后的落点。
 *
 * 用 `useSearchParams` 而不是「effect 里读 window.location.search 再 setState」
 * ——后者触发级联渲染，eslint 的 react-hooks/set-state-in-effect 就是报这个。
 *
 * `useSearchParams` 会让整条路由失去静态预渲染能力，**必须有 Suspense
 * 边界**（由 AuthGuard 的调用处提供）。曾经在这里写「调用方是 Server
 * Component 所以不需要边界」——错的：本组的 /error-404 会被静态预渲染，
 * next build 直接以 missing-suspense-with-csr-bailout 失败。
 */
function useDestination(): string {
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const query = searchParams.toString()
  return query ? `${pathname ?? '/'}?${query}` : (pathname ?? '/')
}

/**
 * 占位骨架。给一个 8x8 的灰块网格，而不是 `null`——
 * 白屏让用户以为页面坏了，骨架至少说明「正在加载」。
 * 纯内联样式，不引 CSS module：这个组件只在非登录态出现一次，
 * 为它建一套样式文件不划算（且它是 client-only 的，本来就不进首屏 CSS）。
 */
function FullPageSkeleton() {
  return (
    <div
      aria-busy="true"
      aria-label="加载中"
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))',
        gap: '1rem',
        padding: '2rem',
      }}
    >
      {Array.from({ length: 8 }, (_, i) => (
        <div
          key={i}
          style={{
            height: 120,
            borderRadius: '0.75rem',
            background: 'var(--token-surface-container-low, #f3f4f5)',
          }}
        />
      ))}
    </div>
  )
}

/**
 * 后端问不到时的界面。给出原因与重试，而不是把用户送去登录页——
 * 他的 session 可能完全正常，只是这次请求没成功。
 */
function Unreachable({ onRetry }: { onRetry: () => Promise<void> }) {
  const [busy, setBusy] = React.useState(false)

  return (
    <div
      role="alert"
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: '0.75rem',
        minHeight: '60vh',
        padding: '2rem',
        textAlign: 'center',
      }}
    >
      <p style={{ fontSize: '1rem', color: 'var(--token-on-surface, #191c1d)' }}>
        连不上服务端，暂时无法确认登录状态。
      </p>
      <p style={{ fontSize: '0.875rem', color: 'var(--token-secondary, #575e70)' }}>
        这通常是后端正在重启或网络不通，不是登录失效——不必重新登录。
      </p>
      <button
        type="button"
        disabled={busy}
        onClick={() => {
          setBusy(true)
          void onRetry().finally(() => setBusy(false))
        }}
        style={{
          padding: '0.5rem 1rem',
          borderRadius: '0.5rem',
          border: 'none',
          cursor: busy ? 'default' : 'pointer',
          background: 'var(--token-primary-container, #7039f9)',
          color: 'var(--token-on-primary, #ffffff)',
          opacity: busy ? 0.6 : 1,
        }}
      >
        {busy ? '重试中…' : '重试'}
      </button>
    </div>
  )
}
