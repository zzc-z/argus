import { PageHeader } from '@/components/common/PageHeader'
import type { PageLayoutProps } from './types'
import styles from './index.module.css'

export type { PageLayoutProps } from './types'

/**
 * PageLayout — page-level structural wrapper.
 *
 *   <PageLayout header={{ title, enLabel, stats, actions }}>
 *     {/* page body *\/}
 *   </PageLayout>
 *
 * Composes:
 *   1. <PageHeader> (if `header` provided) — title / chip / subtitle / actions
 *   2. <main.body> — page content with vertical rhythm
 *
 * This component lives inside the (dashboard) layout's <main class="mainInner">,
 * which already provides padding-inline (1.5rem) + padding-bottom (2rem) +
 * padding-top (3.5rem via the outer <main class="main">).
 */
export function PageLayout({ header, children, className }: PageLayoutProps) {
  return (
    <div className={className}>
      {header ? <PageHeader {...header} /> : null}
      <div className={styles.body}>{children}</div>
    </div>
  )
}
