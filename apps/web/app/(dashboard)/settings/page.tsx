'use client'

import * as React from 'react'
import {
  memoryItemsSeed,
  memoryRulesSeed,
  providerStatusesSeed,
  type MemoryFilter,
  type MemoryItem,
  type MemoryRule,
  type ProviderStatus,
  type SettingsNavId,
} from './mock'
import { SettingsSidebar } from './components/SettingsSidebar'
import { ProfileBanner } from './components/ProfileBanner'
import { LongTermMemorySection } from './components/LongTermMemorySection'
import { MemoryItemsSection } from './components/MemoryItemsSection'
import { ProviderStatusSection } from './components/ProviderStatusSection'
import styles from './page.module.css'

/**
 * /settings page (design §1-497).
 * Composes:
 *   - SettingsSidebar (left nav + vector index diagnostic)
 *   - ProfileBanner (top profile snippet)
 *   - LongTermMemorySection (master toggle + cross-topic sub-toggle + 3 rules)
 *   - MemoryItemsSection (filter tabs + search + 4 memory items + bulk actions)
 *   - ProviderStatusSection (4 provider badges)
 *
 * State is local to this page; no API calls. All destructive actions gated
 * by `window.confirm` inside each component.
 */
export default function SettingsPage() {
  const [activeNav, setActiveNav] = React.useState<SettingsNavId>('memory')
  const [masterEnabled, setMasterEnabled] = React.useState(true)
  const [crossTopicReasoning, setCrossTopicReasoning] = React.useState(true)
  const [rules, setRules] = React.useState<MemoryRule[]>(() => [...memoryRulesSeed])
  const [items, setItems] = React.useState<MemoryItem[]>(() => [...memoryItemsSeed])
  const [providers] = React.useState<ProviderStatus[]>(() => [...providerStatusesSeed])
  const [activeFilter, setActiveFilter] = React.useState<MemoryFilter['id']>('all')
  const [searchQuery, setSearchQuery] = React.useState('')

  /* ── Counts for filter tab labels (design §270-285) ── */
  const countsByFilter = React.useMemo(() => {
    const counts: Record<MemoryFilter['id'], number> = {
      all: items.length,
      preference: 0,
      reflection: 0,
      definition: 0,
      correction: 0,
    }
    for (const it of items) counts[it.kind] += 1
    return counts
  }, [items])

  /* ── Filtered + searched view of items ── */
  const visibleItems = React.useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    return items.filter((it) => {
      const matchesKind = activeFilter === 'all' || it.kind === activeFilter
      const matchesQuery =
        q.length === 0 || it.body.toLowerCase().includes(q) || it.memId.toLowerCase().includes(q)
      return matchesKind && matchesQuery
    })
  }, [items, activeFilter, searchQuery])

  /* ── Rule handlers ── */
  const handleRuleToggle = React.useCallback((id: string, next: boolean) => {
    setRules((prev) => prev.map((r) => (r.id === id ? { ...r, enabled: next } : r)))
  }, [])

  const handleRuleEdit = React.useCallback((id: string) => {
    if (typeof window === 'undefined') return
    window.alert(`（Mock）打开准则编辑器: ${id}`)
  }, [])

  const handleRuleDelete = React.useCallback((id: string) => {
    setRules((prev) => prev.filter((r) => r.id !== id))
  }, [])

  const handleAddRule = React.useCallback(() => {
    if (typeof window === 'undefined') return
    window.alert('（Mock）新建准则弹窗将在此打开')
  }, [])

  /* ── Memory item handlers ── */
  const handleAddItem = React.useCallback(() => {
    if (typeof window === 'undefined') return
    window.alert('（Mock）手动添加记忆项表单将在此打开')
  }, [])

  const handleEditItem = React.useCallback((id: string) => {
    if (typeof window === 'undefined') return
    window.alert(`（Mock）编辑记忆项: ${id}`)
  }, [])

  const handleDeleteItem = React.useCallback((id: string) => {
    setItems((prev) => prev.filter((it) => it.id !== id))
  }, [])

  const handleExportJson = React.useCallback(() => {
    if (typeof window === 'undefined') return
    window.alert('（Mock）导出记忆图谱 JSON')
  }, [])

  const handleClearAll = React.useCallback(() => {
    setItems([])
  }, [])

  /* ── Profile banner handlers ── */
  const handleManageProfile = React.useCallback(() => {
    if (typeof window === 'undefined') return
    window.alert('（Mock）打开资料管理弹窗')
  }, [])

  const handleSyncSso = React.useCallback(() => {
    if (typeof window === 'undefined') return
    const ok = window.confirm('确认触发 SSO 凭据同步？')
    if (ok) window.alert('（Mock）已触发 SSO 同步')
  }, [])

  /* ── Provider handlers ── */
  const handleConfigureProviders = React.useCallback(() => {
    if (typeof window === 'undefined') return
    window.alert('（Mock）跳转到「模型与 API 密钥」')
    setActiveNav('api-keys')
  }, [])

  return (
    <div className={styles.root}>
      {/* Page header (design §7-15) */}
      <header className={styles.pageHeader}>
        <div className={styles.pageTitleRow}>
          <h1 className={`${styles.pageTitle} font-headline-lg text-on-surface font-semibold`}>
            系统设置
          </h1>
          <span className={`${styles.pageTitleMeta} font-code text-secondary`}>/ Settings</span>
        </div>
        <p className={`${styles.pageDesc} font-body-sm text-secondary`}>
          管理研究员个人偏好、长短期记忆图谱、多模型协同 API 及系统集成
        </p>
      </header>

      {/* Main grid: left nav + right panels (design §17) */}
      <div className={styles.grid}>
        <aside className={styles.left}>
          <SettingsSidebar activeId={activeNav} onSelect={setActiveNav} />
        </aside>

        <div className={styles.right}>
          <ProfileBanner onManageProfile={handleManageProfile} onSyncSso={handleSyncSso} />
          <LongTermMemorySection
            masterEnabled={masterEnabled}
            crossTopicReasoning={crossTopicReasoning}
            rules={rules}
            onMasterChange={setMasterEnabled}
            onCrossTopicChange={setCrossTopicReasoning}
            onRuleToggle={handleRuleToggle}
            onRuleEdit={handleRuleEdit}
            onRuleDelete={handleRuleDelete}
            onAddRule={handleAddRule}
          />
          <MemoryItemsSection
            total={items.length}
            countsByFilter={countsByFilter}
            activeFilter={activeFilter}
            onFilterChange={setActiveFilter}
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
            items={visibleItems}
            onAddItem={handleAddItem}
            onEditItem={handleEditItem}
            onDeleteItem={handleDeleteItem}
            onExportJson={handleExportJson}
            onClearAll={handleClearAll}
          />
          <ProviderStatusSection providers={providers} onConfigure={handleConfigureProviders} />
        </div>
      </div>
    </div>
  )
}
