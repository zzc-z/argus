'use client'

import { useState } from 'react'

import { PageLayout } from '@/components/common/PageLayout'
import { Toast, type ToastTone } from '@/components/common/Toast'
import { SettingsSidebar } from './components/SettingsSidebar'
import { ProfileBanner } from './components/ProfileBanner'
import { ProviderStatusSection } from './components/ProviderStatusSection'
import { CredentialsPanel } from './components/CredentialsPanel'

import {
  toProfileBanner,
  toProviderStatus,
  toVectorIndexDiagnostic,
  type SettingsNavId,
} from './view'
import { useSettingsStatus } from './useSettingsStatus'
import { useCredentials } from './useCredentials'
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
  const [activeNav, setActiveNav] = useState<SettingsNavId>('profile')
  const { requestId, result, reload } = useSettingsStatus()
  const credentialsState = useCredentials()
  // 保存结果的提示。挂在页面层而不是面板里——面板会随左侧导航切换
  // 而卸载，提示跟着消失就说不出「保存成了」。
  const [toast, setToast] = useState<{ message: string; tone: ToastTone } | null>(null)

  /* ── 后端数据 → 组件消费的形状。旧请求的结果一律不认 ── */
  const isCurrent = result.requestId === requestId
  const ready = isCurrent && result.kind === 'ready' ? result.data : null
  const providers = ready ? ready.providers.map(toProviderStatus) : []
  const diagnostic = ready ? toVectorIndexDiagnostic(ready.vector_index) : null

  /* ── 个人资料：读全局登录态，不重复请求 /me ── */
  const { user } = useUser()
  const profile = toProfileBanner(user)

  /* ── 凭据变了：两份数据源都要刷新 ──
   *
   * 凭据状态（面板里的值）与供应商状态（上面的徽章卡）读的是**两个不同
   * 端点**，但反映的是同一份配置。只刷一个的话，用户会看到「面板说已配置，
   * 徽章说未配置」——自相矛盾。
   */
  const reloadAll = () => {
    credentialsState.reload()
    reload()
  }

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
            // 后端还没有对应接口：如实提示，而不是假装能改。
            onManageProfile={() => setToast({ message: '资料管理尚未接入后端接口', tone: 'info' })}
            onSyncSso={() => setToast({ message: 'SSO 凭据同步尚未接入后端接口', tone: 'info' })}
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

          <ProviderStatusSection
            providers={providers}
            onConfigure={() => setActiveNav('api-keys')}
          />

          {/* 凭据配置：只有选中「模型与 API 密钥」时才展开。
              面板自己管加载 / 出错 / 有数据三态——它与供应商状态是两份
              独立的数据源。 */}
          {activeNav === 'api-keys' && (
            <CredentialsPanel
              state={credentialsState.state}
              // 面板的「重试」只重新拉取，**不弹「配置已保存」**——
              // 什么都没保存却提示保存成功，界面就在骗人。
              onReload={reloadAll}
              // 保存成功后面板会再调 onReload 刷新数据，这里只负责提示。
              onSaved={() => setToast({ message: '配置已保存', tone: 'success' })}
              // 没有任何改动也提示一句，别让用户以为按钮坏了。
              onNothingChanged={() => setToast({ message: '没有需要保存的改动', tone: 'info' })}
              onSaveFailed={(message) =>
                setToast({ message: `保存失败：${message}`, tone: 'error' })
              }
            />
          )}
        </div>
      </div>

      {/* 保存成功的提示挂在页面层，不挂在面板里——
          面板会随左侧导航切换而卸载，提示跟着消失就说不出「保存成了」。 */}
      <Toast message={toast?.message ?? null} tone={toast?.tone} onDismiss={() => setToast(null)} />
    </PageLayout>
  )
}
