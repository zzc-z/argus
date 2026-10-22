'use client'

/**
 * ExploreGrid — 「继续您的研究探索」卡片行。
 *
 * 卡片数据来自后端 `GET /api/v1/reports`（最近生成的报告），由
 * `view.ts` 的 `toExploreReports` 映射成这里的 `ExploreReport` 形状。
 *
 * ## 原来的假字段去哪了
 *
 * 这一版卡片原先带 6 个后端没有的字段，全部删掉而不是编一个值：
 *
 * - `coverImage`（封面图 URL）—— 设计稿用的是一个占位图 URL，库里没有
 *   封面概念。封面改成纯色底 + 装饰图标（`coverIcon`）。
 * - `tags`（两个深色标签）—— 后端没有报告分类。删。
 * - `agents`（「N 位智能体协同」）—— 后端不存每份报告的智能体数。删。
 * - `footer` + `ctaLabel` + `ctaPrimary`（进度文案与 CTA）—— 那个按钮
 *   **点了没反应**，是个假 affordance。现在 CTA 换成跳 `/report/{id}`
 *   的真实链接，footer 换成真实的 token 用量与耗时。
 */

import * as React from 'react'
import Link from 'next/link'
import { IconSpan } from '@/components/common/IconSpan'
import { cn } from '@/lib/utils'
import type { ExploreReport } from '../../view'
import styles from './index.module.css'

export interface ExploreGridProps {
  reports: ExploreReport[]
}

export function ExploreGrid({ reports }: ExploreGridProps) {
  return (
    <section className={styles.root}>
      <header className={styles.head}>
        <div className={styles.headTitle}>
          <IconSpan name="explore" size={20} className={styles.headIcon} />
          <h2 className={`${styles.title} font-headline-md font-semibold tracking-tight`}>
            继续您的研究探索
          </h2>
        </div>
        <div className={styles.headActions}>
          <span className={`${styles.headMeta} font-body-sm`}>最近更新与上下文命中</span>
          <Link
            href="/explore"
            className={cn(styles.cta, styles.ctaPrimary, styles.headCta, 'font-body-sm font-medium')}
          >
            <IconSpan name="add" size={16} />
            <span>新建研究</span>
          </Link>
        </div>
      </header>

      <div className={styles.grid}>
        {reports.map((r) => (
          <article key={r.id} className={styles.card}>
            <div>
              <div className={styles.cover}>
                {/* 封面图 URL 已删（后端没有封面概念），留一个装饰图标。 */}
                <div className={styles.coverOverlay} aria-hidden="true" />
                <div className={styles.coverTags}>
                  <span className={cn(styles.coverTag, styles.coverTagPrimary)}>
                    <IconSpan name={r.coverIcon} size={14} />
                  </span>
                </div>
                <span className={styles.coverTimestamp}>{r.activity}</span>
              </div>

              <h3 className={`${styles.cardTitle} font-headline-sm font-semibold`}>{r.title}</h3>

              <div className={`${styles.statsRow} font-code`}>
                <span className={styles.stat}>
                  <IconSpan name="menu_book" size={15} className={styles.statIconSecondary} />
                  {r.citations} 篇引用
                </span>
                <span aria-hidden="true">·</span>
                <span className={styles.stat}>
                  <IconSpan name="timer" size={15} className={styles.statIconPrimary} />
                  {r.elapsed}
                </span>
              </div>
            </div>

            <div className={styles.footer}>
              <span className={`${styles.footerLabel} font-code`}>
                {r.inputTokens.toLocaleString('zh-CN')} 输入 / {r.outputTokens.toLocaleString('zh-CN')}{' '}
                输出 Token
              </span>
              <Link
                href={`/report/${r.id}`}
                className={cn(styles.cta, styles.ctaPrimary, 'font-body-sm font-medium')}
              >
                <IconSpan name="visibility" size={16} />
                <span>查看报告</span>
              </Link>
            </div>
          </article>
        ))}
      </div>
    </section>
  )
}
