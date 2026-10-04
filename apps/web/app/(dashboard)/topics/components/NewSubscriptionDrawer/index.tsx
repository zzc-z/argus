'use client'

import * as React from 'react'
import { useState } from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import type { NewNotificationInput } from '@/lib/notifications'
import styles from './index.module.css'

/**
 * Right-side slide-over drawer for creating a new subscription.
 * Form fields are controlled; on submit, calls `onActivate(input)` so the
 * page can push a notification into the cross-page store.
 */
export interface NewSubscriptionDrawerProps {
  open: boolean
  onClose: () => void
  /** Called with the assembled payload when the user clicks 确认并激活订阅. */
  onActivate?: (input: NewNotificationInput) => void
}

const SOURCE_OPTIONS = [
  { id: 'preprint', title: '学术预印本库', meta: 'Arxiv (cs.AI, cs.LG, Quant-ph)', checked: true },
  { id: 'rss', title: '技术博客与官方 RSS', meta: 'OpenAI, DeepMind, Anthropic', checked: true },
  { id: 'regulator', title: '官方监管与上市公司财报', meta: 'SEC EDGAR, 欧盟公报数据库', checked: true },
  { id: 'social', title: '专家推特与 Discord 讨论', meta: '高信誉核心工程师 List', checked: false },
] as const

const FREQUENCY_OPTIONS = [
  { id: 'realtime', icon: 'bolt', title: '实时推送', meta: '≤ 5 分钟', checked: true, accent: true },
  { id: '6h', icon: 'timelapse', title: '每 6 小时', meta: '标准巡检', checked: false, accent: false },
  { id: 'daily', icon: 'wb_sunny', title: '每日晨报', meta: '08:00 汇总', checked: false, accent: false },
  { id: 'weekly', icon: 'calendar_view_week', title: '每周汇总', meta: '周一全量', checked: false, accent: false },
] as const

const FREQUENCY_LABEL: Record<string, string> = {
  realtime: '实时推送',
  '6h': '每 6 小时',
  daily: '每日晨报',
  weekly: '每周汇总',
}

export function NewSubscriptionDrawer({ open, onClose, onActivate }: NewSubscriptionDrawerProps) {
  const [topicName, setTopicName] = useState('')
  const [intent, setIntent] = useState('')
  const [selectedSources, setSelectedSources] = useState<Set<string>>(
    () => new Set(SOURCE_OPTIONS.filter((s) => s.checked).map((s) => s.id)),
  )
  const [frequency, setFrequency] = useState<string>('realtime')

  const toggleSource = (id: string) => {
    setSelectedSources((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handleActivate = () => {
    const name = topicName.trim() || '新研究课题'
    const freq = FREQUENCY_LABEL[frequency] ?? frequency
    const sourceList = SOURCE_OPTIONS.filter((s) => selectedSources.has(s.id))
      .map((s) => s.title)
      .join('、')
    onActivate?.({
      category: 'subscriptions',
      severity: 'info',
      icon: 'radar',
      tag: '【主题动态】',
      title: `${name} 已激活`,
      body: `${freq} 巡检 · ${sourceList || '暂未配置信源'} · ${intent.trim() || '尚未填写研究意图'}`,
      chips: { topic: name, source: sourceList || '—', sentiment: '监控中' },
    })
  }

  return (
    <div
      className={`${styles.root} ${open ? styles.rootOpen : ''}`}
      aria-hidden={!open}
    >
      <button
        type="button"
        className={styles.backdrop}
        onClick={onClose}
        tabIndex={open ? 0 : -1}
        aria-label="关闭抽屉"
      />
      <div className={styles.panelWrap}>
        <aside
          className={`${styles.panel} ${open ? styles.panelOpen : ''}`}
          role="dialog"
          aria-label="新建研究课题订阅"
        >
          <header className={styles.header}>
            <div className={styles.headerTitle}>
              <span className={styles.headerIconWrap}>
                <IconSpan name="tune" size={20} />
              </span>
              <div className={styles.headerCopy}>
                <h2 className={styles.title}>新建研究课题订阅</h2>
                <span className={styles.subtitle}>配置自主智能体巡检拓扑与信息沉淀管道</span>
              </div>
            </div>
            <button type="button" className={styles.closeBtn} onClick={onClose} aria-label="关闭">
              <IconSpan name="close" size={22} />
            </button>
          </header>

          <div className={styles.body}>
            <div className={styles.section}>
              <label className={styles.sectionLabel}>
                <span>课题名称 (Topic Identifier)</span>
                <span className={styles.required}>必填</span>
              </label>
              <input
                type="text"
                value={topicName}
                onChange={(e) => setTopicName(e.target.value)}
                placeholder="例如：自回归视频生成大模型架构与算力成本"
                className={`${styles.input} ${styles.inputMd}`}
                data-testid="topic-name"
              />
            </div>

            <div className={styles.section}>
              <label className={styles.sectionLabel}>
                <span>监控意图与范围描述 (Research Intent)</span>
              </label>
              <textarea
                rows={3}
                value={intent}
                onChange={(e) => setIntent(e.target.value)}
                placeholder="明确该课题需核心捕获的关键事件、论文类型、技术突破点，用于引导 Agent 进行语义相关度评分..."
                className={`${styles.input} ${styles.textarea}`}
              />
            </div>

            <div className={styles.section}>
              <div className={styles.sectionHead}>
                <label className={styles.sectionLabel}>信源配置 (Multi-Source Connectors)</label>
                <span className={styles.sectionMeta}>已勾选 {selectedSources.size} 类</span>
              </div>
              <div className={styles.sourceGrid}>
                {SOURCE_OPTIONS.map((s) => (
                  <label key={s.id} className={styles.sourceCard}>
                    <input
                      type="checkbox"
                      checked={selectedSources.has(s.id)}
                      onChange={() => toggleSource(s.id)}
                      className={styles.sourceCheckbox}
                    />
                    <div className={styles.sourceCopy}>
                      <span className={styles.sourceTitle}>{s.title}</span>
                      <span className={styles.sourceMeta}>{s.meta}</span>
                    </div>
                  </label>
                ))}
              </div>
            </div>

            <div className={styles.section}>
              <label className={styles.sectionLabel}>
                <span>巡检更新频率 (Inspection Schedule)</span>
              </label>
              <div className={styles.frequencyGrid}>
                {FREQUENCY_OPTIONS.map((f) => (
                  <label key={f.id} className={styles.frequencyCard}>
                    <input
                      type="radio"
                      name="frequency"
                      value={f.id}
                      checked={frequency === f.id}
                      onChange={() => setFrequency(f.id)}
                      className={styles.frequencyRadio}
                    />
                    <IconSpan
                      name={f.icon}
                      size={18}
                      className={f.accent ? 'text-primary' : 'text-secondary'}
                    />
                    <span className={styles.frequencyTitle}>{f.title}</span>
                    <span className={styles.frequencyMeta}>{f.meta}</span>
                  </label>
                ))}
              </div>
            </div>

            <div className={styles.policyCard}>
              <span className={styles.policyLabel}>
                <IconSpan name="smart_toy" size={18} className="text-primary" />
                智能体协同策略 (Agent Synthesis Policy)
              </span>
              <div className={styles.policyOptions}>
                <label className={styles.policyOption}>
                  <input
                    type="radio"
                    name="policy"
                    defaultChecked
                    className={styles.policyRadio}
                  />
                  <span>自动执行 DAG 提炼并生成阶段性研究简报</span>
                </label>
                <label className={styles.policyOption}>
                  <input type="radio" name="policy" className={styles.policyRadio} />
                  <span>仅推送原始高置信度事件，保留人工二次介入</span>
                </label>
              </div>
            </div>
          </div>

          <footer className={styles.footer}>
            <button type="button" className={styles.cancelBtn} onClick={onClose}>
              取消
            </button>
            <div className={styles.footerActions}>
              <button type="button" className={styles.secondaryBtn}>
                保存并测试信源
              </button>
              <button
                type="button"
                className={styles.primaryBtn}
                onClick={handleActivate}
                data-testid="activate-btn"
              >
                确认并激活订阅
              </button>
            </div>
          </footer>
        </aside>
      </div>
    </div>
  )
}
