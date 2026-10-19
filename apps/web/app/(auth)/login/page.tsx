import type { Metadata } from 'next'

import { LoginScreen } from './components/LoginScreen'

// 根 layout 是 default + template，这一页给短名，渲染成「登录 | Argus」。
// metadata 只能在 server component 里导出，所以交互外壳拆到 LoginScreen。
export const metadata: Metadata = { title: '登录' }

export default function LoginPage() {
  return <LoginScreen />
}
