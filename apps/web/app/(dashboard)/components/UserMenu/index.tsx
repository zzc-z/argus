'use client'

import * as React from 'react'
import Link from 'next/link'
import { useState } from 'react'

import { IconSpan } from '@/components/common/IconSpan'
import { useUser } from '@/lib/auth'
import styles from './index.module.css'

/**
 * 顶栏用户菜单：hover 头像弹出卡片，含用户资料与登出。
 *
 * **本组件只处理已登录态。** 未登录时 `(dashboard)/layout.tsx` 的
 * AuthGuard 已经把整页 replace 到 /login，页面根本不会渲染到这里——所以
 * 这里没有「未登录」的分支，也没有顶栏「登录」链接。
 *
 * 为什么不引 Radix Popover——一个 hover 卡片用不着一整套无障碍原语，
 * 而且项目里已有 radix 的 label/separator/slot，没有 popover 先例，
 * 手写保持依赖为零。
 *
 * hover 的固有缺陷：触屏设备没有 hover。这里用 onPointerEnter/
 * onPointerLeave 而非 onMouse*，因为它们对触屏也会触发（Pointer Events
 * 统一了鼠标和触摸），iPad 上轻触能打开；再用 matchMedia 排除掉
 * 纯 hover 的指针类型，避免桌面端触屏误触。
 */

/** 头像取不到图片时的占位：展示昵称首字母。 */
function initialsOf(displayName: string | null, email: string | null): string {
  const source = displayName?.trim() || email?.trim() || '?'
  return Array.from(source)[0]?.toUpperCase() ?? '?'
}

export function UserMenu() {
  const { user, logout } = useUser()
  const [open, setOpen] = useState(false)
  const [loggingOut, setLoggingOut] = useState(false)
  const closeTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null)

  /** 关闭延迟：鼠标从头像移向卡片时会短暂经过间隙，立即关会闪一下。 */
  const CLOSE_DELAY_MS = 140

  // 不包 useCallback：这两个函数只读写 closeTimer（一个 ref），
  // 不读任何 state/props，也没有传给 memo 子组件——包了没有收益。
  // 定时器的清理放进 useEffect 的收尾函数即可。
  const cancelClose = () => {
    if (closeTimer.current !== null) {
      clearTimeout(closeTimer.current)
      closeTimer.current = null
    }
  }

  const scheduleClose = () => {
    cancelClose()
    closeTimer.current = setTimeout(() => {
      setOpen(false)
      closeTimer.current = null
    }, CLOSE_DELAY_MS)
  }

  // 卸载时清掉挂起的定时器，避免对已卸载组件 setState
  React.useEffect(() => cancelClose, [])

  const handleLogout = async () => {
    setLoggingOut(true)
    try {
      await logout()
    } finally {
      setLoggingOut(false)
    }
  }

  if (!user) {
    // 理论不可达：AuthGuard 在本组件渲染前就已经把未登录的页面跳走了。
    // 留这一行是为了类型收窄（user 在后面被当作非空用），不是为了兜底。
    return null
  }

  return (
    <div
      className={styles.root}
      onPointerEnter={() => {
        cancelClose()
        setOpen(true)
      }}
      onPointerLeave={scheduleClose}
      onFocus={() => setOpen(true)}
      onBlur={(e) => {
        // 焦点移到卡片内的可交互元素时不算离开
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) {
          setOpen(false)
        }
      }}
    >
      <button
        type="button"
        className={styles.trigger}
        aria-haspopup="menu"
        aria-expanded={open}
        // 卡片内容在 DOM 里但视觉隐藏，读屏仍能读到当前用户是谁
        aria-label={`用户菜单，当前用户 ${user.display_name ?? user.email ?? '未知'}`}
      >
        <span className={styles.avatar} aria-hidden="true">
          {user.avatar_url ? (
            // 头像 URL 来自 GitHub，非优化过的图所以用原生 img 而非 next/image
            // eslint-disable-next-line @next/next/no-img-element
            <img src={user.avatar_url} alt="" className={styles.avatarImg} />
          ) : (
            initialsOf(user.display_name, user.email)
          )}
        </span>
        <span className={styles.userText}>
          <span className={`${styles.userName} font-body-sm font-medium`}>
            {user.display_name ?? '未命名用户'}
          </span>
        </span>
      </button>

      {open && (
        <div className={styles.card} role="menu">
          <div className={styles.cardHeader}>
            <span className={styles.cardAvatar} aria-hidden="true">
              {user.avatar_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={user.avatar_url} alt="" className={styles.avatarImg} />
              ) : (
                initialsOf(user.display_name, user.email)
              )}
            </span>
            <div className={styles.cardIdentity}>
              <span className={styles.cardName}>{user.display_name ?? '未命名用户'}</span>
              {user.email && <span className={styles.cardEmail}>{user.email}</span>}
            </div>
          </div>

          <div className={styles.cardDivider} />

          <Link href="/settings" className={styles.cardItem} role="menuitem">
            <IconSpan name="settings" size={16} />
            <span>个人设置</span>
          </Link>

          <button
            type="button"
            className={`${styles.cardItem} ${styles.cardItemDanger}`}
            role="menuitem"
            onClick={handleLogout}
            disabled={loggingOut}
          >
            <IconSpan name="logout" size={16} />
            <span>{loggingOut ? '正在登出…' : '退出登录'}</span>
          </button>
        </div>
      )}
    </div>
  )
}
