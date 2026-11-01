import type { Metadata } from 'next'
import { Geist, Inter, JetBrains_Mono } from 'next/font/google'
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

// Inter 是 explore 页的 UI 主字体。
//
// **必须在这里声明，不能在 explore/page.tsx 里另起一个 next/font/google
// 导入。** Next 16 规定 `next/font/google` 全项目只能有**一个**导入入口
// （字体内联模块由它统一生成，多个入口会报
// "next/font/google queries have exactly one entry"，
// 页面直接 500）。
//
// 之前 explore/page.tsx 自己 import 了 Inter —— 那时能用，是因为
// 依赖版本较旧；升级到 Next 16.3.8 后就变成 500。
const inter = Inter({
  subsets: ['latin'],
  variable: '--font-inter',
  display: 'swap',
  weight: ['400', '500', '600'],
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
    <html
      lang="zh-CN"
      className={`${geist.variable} ${jetbrainsMono.variable} ${inter.variable} h-full`}
    >
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
