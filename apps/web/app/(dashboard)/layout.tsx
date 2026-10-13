import * as React from 'react'
import Link from 'next/link'

import { IconSpan } from '@/components/common/IconSpan'
import { ArgusMark } from '@/components/common/ArgusMark'
import { ThemeToggle } from '@/components/common/ThemeToggle'

import { UserMenu } from './components/UserMenu'
import { QuickKeys } from './components/QuickKeys'

import { NavLink } from './NavLink'
import styles from './layout.module.css'

/**
 * Dashboard route group layout — sidebar (fixed left) + top header (fixed top)
 * + main scroll area. Both chrome pieces are 1:1 from argus_report_detail's
 * outer chrome; the right `children` is the page body.
 */
export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <div className={styles.sidebarTop}>
          <div className={styles.brandRow}>
            <div className={styles.brandLeft}>
              <div className={styles.brandMark}>
                <ArgusMark size={20} />
              </div>
              <div className={styles.brandText}>
                <span className={`${styles.brandName} font-headline-sm`}>Argus</span>
                <span className={`${styles.brandSub} font-label-sm`}>Synthesizer Core</span>
              </div>
            </div>
            <span className={`${styles.versionChip} font-code`}>v2.4</span>
          </div>

          <button type="button" className={styles.workspaceSwitcher}>
            <div className={styles.workspaceLeft}>
              <IconSpan name="layers" size={18} />
              <span className="font-body-sm truncate">Argus Research Workspace</span>
            </div>
            <IconSpan name="unfold_more" size={16} />
          </button>

          <div className={styles.divider} />

          <div className={styles.navWrap}>
            <span className={`${styles.navHeading} font-label-sm uppercase tracking-wider`}>
              Navigation
            </span>
            <nav className={styles.nav}>
              <NavLink href="/dashboard" icon="dashboard" label="Dashboard 首页" />
              <NavLink href="/explore" icon="explore" label="研究工作台" />
              <NavLink href="/reports" icon="article" label="报告列表" />
              <NavLink href="/topics" icon="rss_feed" label="主题订阅" />
              <NavLink href="/sources" icon="database" label="资料库" />
              <NavLink href="/notifications" icon="notifications" label="通知中心" />
              <NavLink href="/settings" icon="tune" label="设置" />
            </nav>
          </div>
        </div>

        <div className={styles.sidebarFoot}>
          <div className={styles.clusterCard}>
            <div className={styles.clusterTop}>
              <span className="font-label-sm text-secondary">Agent Run Cluster</span>
              <span className={`${styles.clusterActive} font-code`}>Active</span>
            </div>
            <div className={styles.progressTrack}>
              <div className={styles.progressFill} style={{ width: '66.66%' }} />
            </div>
            <div className={`${styles.clusterMeta} font-code`}>
              <span>DAG: 14 Nodes</span>
              <span>99.4% Latency</span>
            </div>
          </div>
          <div className={`${styles.sessionRow} font-code`}>
            <span>Session #AR-882</span>
            <button type="button" className={styles.sessionIcon} aria-label="打开终端">
              <IconSpan name="terminal" size={16} />
            </button>
          </div>
        </div>
      </aside>

      <div className={styles.content}>
        <header className={styles.topbar}>
          <div className={styles.topbarLeft}>
            <Link href="/explore" className={styles.searchBox}>
              <IconSpan name="search" size={18} />
              <span className={`${styles.searchText} font-body-sm`}>
                快速检索节点、研究模型或报告...
              </span>
              <kbd className={`${styles.searchKbd} font-code`}>⌘K</kbd>
            </Link>
            <div className={styles.statusPill}>
              <span className={styles.statusDot} aria-hidden="true" />
              <span className={`${styles.statusText} font-label-sm`}>就绪</span>
              <span className={styles.statusSep}>·</span>
              <span className={`${styles.statusRate} font-code`}>8.2k tokens/s</span>
            </div>
          </div>
          <div className={styles.topbarRight}>
            <button type="button" className={styles.iconBtn} aria-label="通知">
              <IconSpan name="notifications" size={20} />
              <span className={styles.notifDot} aria-hidden="true" />
            </button>
            <button type="button" className={styles.iconBtn} aria-label="帮助">
              <IconSpan name="help_outline" size={20} />
            </button>
            <div className={styles.topbarDivider} aria-hidden="true" />
            <ThemeToggle />
            <UserMenu />
          </div>
        </header>

        <main className={styles.main}>
          <div className={styles.mainInner}>
            <PageHeaderChrome />
            {children}
          </div>
        </main>
      </div>
      <QuickKeys />
    </div>
  )
}

/**
 * Renders the breadcrumb + quick action row at the top of every dashboard page.
 * The report page imports its own richer header; for everything else we just
 * leave an empty slot. This exists so the layout owns the structural
 * breadcrumb slot without forcing pages to repeat chrome.
 */
function PageHeaderChrome() {
  return null
}
