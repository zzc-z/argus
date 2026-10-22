'use client'

import * as React from 'react'
import { useUser } from '@/lib/auth/UserContext'
import styles from './index.module.css'

/**
 * 侧栏底部的当前会话标识。
 *
 * ## 原来这里是什么
 *
 * 写死的 `Session #AR-882` 加一个「打开终端」的图标按钮。那个按钮点了
 * 没反应——**后端没有终端、没有 shell、没有会话列表**。`#AR-882` 也是一个
 * 编出来的编号，跟任何真实的 session id 无关。
 *
 * ## 现在是什么
 *
 * 显示当前登录用户的标识（`users.id` + 邮箱前缀）。这是这一页真能知道的
 * 「谁在用这个系统」。终端按钮删掉——没有的东西不给假 affordance。
 */
export function SessionBadge() {
  const { user } = useUser()

  if (!user) {
    return (
      <div className={`${styles.row} font-code`}>
        <span>读取用户信息…</span>
      </div>
    )
  }

  const label = user.email ? user.email.split('@')[0] : `user-${user.id}`

  return (
    <div className={`${styles.row} font-code`}>
      <span title={user.email ?? undefined}>用户 {label}</span>
    </div>
  )
}
