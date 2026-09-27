'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import { DRAWER_FREQUENCIES, SOURCE_PRESETS, type Frequency } from '../../mock'
import styles from './index.module.css'

const OPEN_EVENT = 'argus:topics:open-drawer'

/**
 * Right slide-over drawer for creating a new subscription.
 *
 * 1:1 with argus_topics/code.html drawer section:
 *   - Header (icon + title + close)
 *   - Section 1 — Topic Identifier (text input)
 *   - Section 2 — Research Intent (textarea)
 *   - Section 3 — Multi-Source Connectors (2-col checkbox cards)
 *   - Section 4 — Inspection Schedule (4-col radio cards)
 *   - Section 5 — Agent Synthesis Policy (2 radios)
 *   - Footer actions (cancel + save-test + activate)
 *
 * Mounted once at the page root; opens via the global keyboard shortcut
 * (TopicsHeader listens for ⌘N) or the page CTA button — both dispatch
 * `argus:topics:open-drawer`. Closes on backdrop click, X button,
 * Cancel / Save button, or Escape key.
 */
export function NewSubscriptionDrawer() {
  const [open, setOpen] = React.useState(false)

  React.useEffect(() => {
    const onOpen = () => setOpen(true)
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener(OPEN_EVENT, onOpen)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener(OPEN_EVENT, onOpen)
      window.removeEventListener('keydown', onKey)
    }
  }, [])

  return (
    <div
      id="drawer-container"
      aria-hidden={!open}
      className={`${styles.shell} ${open ? styles.shellOpen : ''}`}
    >
      <div
        className={`${styles.backdrop} ${open ? styles.backdropOpen : ''}`}
        onClick={() => setOpen(false)}
        aria-hidden="true"
      />
      <div className={styles.anchor}>
        <Drawer open={open} onClose={() => setOpen(false)} />
      </div>
    </div>
  )
}

interface DrawerProps {
  open: boolean
  onClose: () => void
}

function Drawer({ open, onClose }: DrawerProps) {
  const [frequency, setFrequency] = React.useState<Frequency>('realtime')
  const [selectedSources, setSelectedSources] = React.useState<Set<string>>(
    () => new Set(SOURCE_PRESETS.filter((s) => s.defaultChecked).map((s) => s.id)),
  )
  const [policy, setPolicy] = React.useState<'auto' | 'manual'>('auto')

  const toggleSource = (id: string) => {
    setSelectedSources((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <aside
      id="drawer-content"
      role="dialog"
      aria-modal="true"
      aria-label="新建研究课题订阅"
      className={`${styles.panel} ${open ? styles.panelOpen : ''}`}
    >
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <span className={styles.headerIcon}>
            <IconSpan name="tune" size={20} />
          </span>
          <div>
            <h2 className={`${styles.headerTitle} font-headline-md tracking-tight`}>
              新建研究课题订阅
            </h2>
            <span className={`${styles.headerSubtitle} font-label-sm text-secondary`}>
              配置自主智能体巡检拓扑与信息沉淀管道
            </span>
          </div>
        </div>
        <button type="button" className={styles.closeBtn} onClick={onClose} aria-label="关闭">
          <IconSpan name="close" size={22} />
        </button>
      </header>

      <form className={styles.body} onSubmit={(e) => e.preventDefault()}>
        <section className={styles.section}>
          <label className={`${styles.fieldLabel} font-headline-sm font-semibold`}>
            <span>课题名称 (Topic Identifier)</span>
            <span className={`${styles.fieldRequired} font-label-sm`}>必填</span>
          </label>
          <input
            type="text"
            placeholder="例如：自回归视频生成大模型架构与算力成本"
            className={`${styles.fieldInput} font-body-md`}
          />
        </section>

        <section className={styles.section}>
          <label className={`${styles.fieldLabel} font-headline-sm font-semibold`}>
            监控意图与范围描述 (Research Intent)
          </label>
          <textarea
            rows={3}
            placeholder="明确该课题需核心捕获的关键事件、论文类型、技术突破点，用于引导 Agent 进行语义相关度评分..."
            className={`${styles.fieldTextarea} font-body-sm`}
          />
        </section>

        <section className={styles.section}>
          <div className={styles.sectionHead}>
            <label className={`${styles.fieldLabel} font-headline-sm font-semibold`}>
              信源配置 (Multi-Source Connectors)
            </label>
            <span className={`${styles.sectionMeta} font-label-sm text-secondary`}>
              已勾选 {selectedSources.size} 类
            </span>
          </div>
          <div className={styles.sources}>
            {SOURCE_PRESETS.map((src) => {
              const checked = selectedSources.has(src.id)
              return (
                <label
                  key={src.id}
                  className={`${styles.sourceCard} ${checked ? styles.sourceCardChecked : ''}`}
                >
                  <input
                    type="checkbox"
                    className={styles.sourceCheckbox}
                    checked={checked}
                    onChange={() => toggleSource(src.id)}
                  />
                  <div className={styles.sourceText}>
                    <span className={`${styles.sourceLabel} font-body-sm font-medium`}>
                      {src.label}
                    </span>
                    <span className={`${styles.sourceDetail} font-label-sm text-secondary`}>
                      {src.detail}
                    </span>
                  </div>
                </label>
              )
            })}
          </div>
        </section>

        <section className={styles.section}>
          <label className={`${styles.fieldLabel} font-headline-sm font-semibold`}>
            巡检更新频率 (Inspection Schedule)
          </label>
          <div className={styles.freqGrid}>
            {DRAWER_FREQUENCIES.map((opt) => (
              <label
                key={opt.value}
                className={`${styles.freqCard} ${frequency === opt.value ? styles.freqCardChecked : ''}`}
              >
                <input
                  type="radio"
                  name="frequency"
                  value={opt.value}
                  checked={frequency === opt.value}
                  onChange={() => setFrequency(opt.value)}
                  className={styles.srOnly}
                />
                <IconSpan
                  name={opt.icon}
                  size={18}
                  className={
                    opt.iconTone === 'primary'
                      ? `${styles.freqIcon} text-primary`
                      : `${styles.freqIcon} text-secondary`
                  }
                />
                <span className={`${styles.freqLabel} font-body-sm font-medium`}>{opt.label}</span>
                <span className={`${styles.freqDetail} font-label-sm text-secondary`}>
                  {opt.detail}
                </span>
              </label>
            ))}
          </div>
        </section>

        <section className={`${styles.section} ${styles.policySection}`}>
          <span className={`${styles.policyTitle} font-headline-sm font-semibold`}>
            <IconSpan name="smart_toy" size={18} className="text-primary" />
            智能体协同策略 (Agent Synthesis Policy)
          </span>
          <div className={styles.policyList}>
            <label className={styles.policyItem}>
              <input
                type="radio"
                name="policy"
                checked={policy === 'auto'}
                onChange={() => setPolicy('auto')}
                className={styles.policyRadio}
              />
              <span className={`${styles.policyLabel} font-body-sm`}>
                自动执行 DAG 提炼并生成阶段性研究简报
              </span>
            </label>
            <label className={styles.policyItem}>
              <input
                type="radio"
                name="policy"
                checked={policy === 'manual'}
                onChange={() => setPolicy('manual')}
                className={styles.policyRadio}
              />
              <span className={`${styles.policyLabel} font-body-sm`}>
                仅推送原始高置信度事件，保留人工二次介入
              </span>
            </label>
          </div>
        </section>
      </form>

      <footer className={styles.footer}>
        <button type="button" className={`${styles.cancelBtn} font-headline-sm`} onClick={onClose}>
          取消
        </button>
        <div className={styles.footerRight}>
          <button type="button" className={`${styles.secondaryBtn} font-headline-sm`}>
            保存并测试信源
          </button>
          <button
            type="button"
            className={`${styles.primaryBtn} font-headline-sm`}
            onClick={onClose}
          >
            确认并激活订阅
          </button>
        </div>
      </footer>
    </aside>
  )
}
