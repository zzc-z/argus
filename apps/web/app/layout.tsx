import type { Metadata } from 'next'
import { Geist, JetBrains_Mono } from 'next/font/google'
import { NotificationsProvider } from '@/lib/notifications'
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

export const metadata: Metadata = {
  title: '登录 - Argus 多智能体深度研报平台',
  description: '面向工程师与研究员的 AI 洞察引擎',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" className={`${geist.variable} ${jetbrainsMono.variable} h-full`}>
      <head>
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap"
        />
      </head>
      <body className="bg-[var(--token-background)] text-[var(--token-on-background)] min-h-screen antialiased">
        <NotificationsProvider>{children}</NotificationsProvider>
      </body>
    </html>
  )
}
