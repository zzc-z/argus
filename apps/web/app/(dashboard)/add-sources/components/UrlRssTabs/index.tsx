'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import styles from './index.module.css'

export type UrlRssTab = 'url' | 'rss'

export interface UrlRssTabsProps {
  tab: UrlRssTab
  onTabChange: (t: UrlRssTab) => void
}

/**
 * URL fetch + RSS subscribe tabs (mutually exclusive).
 * Both panes render always; visibility is toggled via a hidden class.
 */
export function UrlRssTabs({ tab, onTabChange }: UrlRssTabsProps) {
  return (
    <section className={styles.section}>
      <div className={styles.head}>
        <div className={styles.headLeft}>
          <span className={styles.headDot} />
          <span className={`${styles.headTitle} font-headline-sm`}>网络链接与实时数据流</span>
        </div>
        <div className={styles.tabSwitch} role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'url'}
            onClick={() => onTabChange('url')}
            className={`${styles.tabBtn} ${tab === 'url' ? styles.tabBtnActive : ''} font-label-sm`}
          >
            单页面深度抓取
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'rss'}
            onClick={() => onTabChange('rss')}
            className={`${styles.tabBtn} ${tab === 'rss' ? styles.tabBtnActive : ''} font-label-sm`}
          >
            RSS / Atom 订阅源
          </button>
        </div>
      </div>

      {/* URL pane */}
      <div
        className={`${styles.pane} ${tab === 'url' ? '' : styles.paneHidden}`}
        role="tabpanel"
        aria-hidden={tab !== 'url'}
      >
        <div className={styles.urlRow}>
          <div className={styles.urlInputWrap}>
            <span className={styles.urlIcon}>
              <IconSpan name="link" size={18} className="text-secondary" />
            </span>
            <input
              type="text"
              className={`${styles.urlInput} font-body-sm`}
              defaultValue="https://semianalysis.com/2026/02/foundry-packaging-inflection"
              placeholder="https://arxiv.org/abs/2403... 或任意新闻研报地址"
            />
          </div>
          <button type="button" className={`${styles.fetchBtn} font-body-sm`}>
            <IconSpan name="downloading" size={18} />
            <span>抓取并解析</span>
          </button>
        </div>
        <div className={styles.toggles}>
          <CheckToggle label="启用无头浏览器渲染 (JS Hydrated)" defaultChecked />
          <CheckToggle label="提取文章内嵌高清图表与 SVG" defaultChecked />
          <span className={`${styles.togglesMeta} font-code hidden sm:inline`}>
            Playwright Core v1.42
          </span>
        </div>
      </div>

      {/* RSS pane */}
      <div
        className={`${styles.pane} ${tab === 'rss' ? '' : styles.paneHidden}`}
        role="tabpanel"
        aria-hidden={tab !== 'rss'}
      >
        <div className={styles.rssRow}>
          <div className={styles.urlInputWrap}>
            <span className={styles.urlIcon}>
              <IconSpan name="rss_feed" size={18} className="text-secondary" />
            </span>
            <input
              type="text"
              className={`${styles.urlInput} font-body-sm`}
              placeholder="https://domain.com/feed.xml 或 Substack RSS 链接"
            />
          </div>
          <select className={`${styles.periodSelect} font-body-sm`} defaultValue="1h">
            <option value="1h">周期: 每小时 (1h)</option>
            <option value="6h">周期: 每 6 小时</option>
            <option value="24h">周期: 每天 (24h)</option>
          </select>
          <button type="button" className={`${styles.subscribeBtn} font-body-sm`}>
            <IconSpan name="add" size={18} />
            <span>验证并订阅</span>
          </button>
        </div>
        <p className={`${styles.rssNote} font-label-sm`}>
          支持 Atom, RSS 2.0 及 JSON Feed 自动更新并生成语义向量图谱增量
        </p>
      </div>
    </section>
  )
}

function CheckToggle({ label, defaultChecked }: { label: string; defaultChecked?: boolean }) {
  return (
    <label className={styles.toggleLabel}>
      <input type="checkbox" defaultChecked={defaultChecked} className="peer sr-only" />
      <span className={styles.toggleBox}>
        <IconSpan name="check" size={14} className="text-on-primary" />
      </span>
      <span className={`${styles.toggleText} font-body-sm`}>{label}</span>
    </label>
  )
}
