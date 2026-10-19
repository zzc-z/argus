import type { Metadata } from 'next'
import { Geist, JetBrains_Mono } from 'next/font/google'
import { NotificationsProvider } from '@/lib/notifications'
import { UserProvider } from '@/lib/auth'
import './globals.css'

const geist = Geist({
  subsets: ['latin'],
  variable: '--font-geist',
  display: 'swap',
})

const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-jetbrains-mono',
  display: 'swap',
})

// 这里原本写死 `'登录 - Argus 多智能体深度研报平台'`——所有页签（包括
// add-sources / sources）都显示「登录」，是登录页遗留的默认值。
// 用 template：子路由的 title 会顶在前面，只有 login 页自己需要完整标题。
export const metadata: Metadata = {
  title: {
    default: 'Argus 多智能体深度研报平台',
    template: '%s | Argus',
  },
  description: '面向工程师与研究员的 AI 洞察引擎',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" className={`${geist.variable} ${jetbrainsMono.variable} h-full`}>
      {/* 字体已由上方 next/font 的 geist / jetbrainsMono 变量注入。
          不要再加 Google Fonts 的 <link>——那会重复请求一次，
          并绕过 next/font 的自托管与预加载优化。 */}
      <body className="min-h-screen bg-[var(--token-background)] text-[var(--token-on-background)] antialiased">
        <UserProvider>
          <NotificationsProvider>{children}</NotificationsProvider>
        </UserProvider>
      </body>
    </html>
  )
}
