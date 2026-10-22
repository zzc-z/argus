'use client'

import * as React from 'react'

import { PageLayout } from '@/components/common/PageLayout'
import { SettingsSidebar } from './components/SettingsSidebar'
import { ProfileBanner } from './components/ProfileBanner'
import { ProviderStatusSection } from './components/ProviderStatusSection'

import {
  toProfileBanner,
  toProviderStatus,
  toVectorIndexDiagnostic,
  type SettingsNavId,
} from './view'
import { useSettingsStatus } from './useSettingsStatus'
import { useUser } from '@/lib/auth'

import styles from './page.module.css'

/**
 * /settings page (design §1-497).
 * Composes:
 *   - SettingsSidebar (left nav + vector index diagnostic)
 *   - ProfileBanner (top profile snippet)
 *   - ProviderStatusSection (provider configuration badges)
 *
 * ## 数据源
 *
 * - `GET /api/v1/settings/status` → 供应商配置状态 + 向量索引规模。
 * - `GET /api/v1/me` → 个人资料。**不重复请求**：全局 `UserProvider`
 *   （`lib/auth/UserContext.tsx`）已经拉过同一个端点并缓存了结果，
 *   这里直接读 context。
 *
 * 长期记忆规则区与记忆条目区已整块删除：后端没有对应的数据源
 * （无 memory_rules 表），页面不该画读不到的数据。
 */
export default function SettingsPage() {
  const [activeNav, setActiveNav] = React.useState<SettingsNavId>('profile')
  const { requestId, result, reload } = useSettingsStatus()

  /* ── 后端数据 → 组件消费的形状。旧请求的结果一律不认 ── */
  const isCurrent = result.requestId === requestId
  const providers = React.useMemo(
    () => (isCurrent && result.kind === 'ready' ? result.data.providers.map(toProviderStatus) : []),
    [isCurrent, result],
  )
  const diagnostic = React.useMemo(
    () =>
      isCurrent && result.kind === 'ready' ? toVectorIndexDiagnostic(result.data.vector_index) : null,
    [isCurrent, result],
  )

  /* ── 个人资料：读全局登录态，不重复请求 /me ── */
  const { user } = useUser()
  const profile = React.useMemo(() => toProfileBanner(user), [user])

  /* ── 操作按钮：后端还没有对应接口，如实说明而不是假装能改 ── */
  const handleManageProfile = React.useCallback(() => {
    if (typeof window === 'undefined') return
    window.alert('资料管理尚未接入后端接口')
  }, [])

  const handleSyncSso = React.useCallback(() => {
    if (typeof window === 'undefined') return
    window.alert('SSO 凭据同步尚未接入后端接口')
  }, [])

  const handleConfigureProviders = React.useCallback(() => {
    if (typeof window === 'undefined') return
    window.alert('模型密钥由后端环境变量配置（.env），暂不支持在页面上修改')
    setActiveNav('api-keys')
  }, [])

  return (
    <PageLayout
      header={{
        title: '系统设置',
        enLabel: '/ Settings',
        subtitle: '管理研究员个人资料、多模型协同 API 及系统集成',
      }}
    >
      {/* Main grid: left nav + right panels (design §17) */}
      <div className={styles.grid}>
        <aside className={styles.left}>
          <SettingsSidebar activeId={activeNav} onSelect={setActiveNav} diagnostic={diagnostic} />
        </aside>

        <div className={styles.right}>
          <ProfileBanner
            profile={profile}
            onManageProfile={handleManageProfile}
            onSyncSso={handleSyncSso}
          />

          {isCurrent && result.kind === 'loading' && (
            <p className={styles.stateText}>正在加载系统状态…</p>
          )}
          {isCurrent && result.kind === 'error' && (
            <p role="alert" className={styles.stateError}>
              系统状态加载失败：{result.message}
              <button type="button" className={styles.retry} onClick={reload}>
                重试
              </button>
            </p>
          )}

          <ProviderStatusSection providers={providers} onConfigure={handleConfigureProviders} />
        </div>
      </div>
    </PageLayout>
  )
}
