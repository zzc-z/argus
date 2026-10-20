'use client'

/**
 * 报告详情页 —— `/report/[id]`。
 *
 * ## 页面能显示什么
 *
 * 后端 `GET /api/v1/reports/{id}` 只返回这些：
 *   - `question`（原始提问，当标题用）· `created_at` · token 数 · 耗时
 *   - `content`（正文 markdown 原文）
 *   - `citations[]`（角标 + 切片信息 + 资料名 + 摘要 + 被引次数）
 *
 * 早期版本这页是整页 mock：规格矩阵、benchmark 柱状图、TCO 成本卡、
 * 决策项表、agent 逐步日志、技术演进时间线、相关报告推荐——**后端一个
 * 字段都没有**，那些组件已随 mock 一起删除。留空壳不如不留。
 *
 * 现在的形态：一个「带角标的 markdown 报告阅读器」+ 右侧引用面板。
 */

import * as React from 'react'
import { use, useCallback, useEffect, useState } from 'react'

import { TitleHero } from './components/TitleHero'
import { ReportHeader } from './components/ReportHeader'
import { ChapterSection } from './components/ChapterSection'
import { SourcesPanel } from './components/SourcesPanel'
import { RelatedReports } from './components/RelatedReports'
import { ResearchDock } from './components/ResearchDock'

import { fetchReport, fetchReports, type ReportDetailV, type ReportSummaryV } from '@/lib/api/reports'
import styles from './page.module.css'

/**
 * 加载结果。
 *
 * 刻意**不**用 `loading | error | ready` 三态判别联合 + 在 effect 里
 * `setState({kind:'loading'})`——那个写法触发级联渲染（React 的
 * `react-hooks/set-state-in-effect` 规则会报）。
 *
 * 改成「结果 + 它属于哪个 id」：加载中与否从 `loadedFor !== reportId`
 * **推导**出来，而不是主动去 set。切换 id 时旧数据还在，但 id 对不上，
 * 页面照样显示加载态——用户看不到上一次报告的内容闪一下。
 */
type LoadResult =
  | { kind: 'error'; message: string; loadedFor: number }
  | { kind: 'ready'; report: ReportDetailV; loadedFor: number }

export default function ReportPage({ params }: { params: Promise<{ id: string }> }) {
  const [result, setResult] = useState<LoadResult | null>(null)
  const [others, setOthers] = useState<ReportSummaryV[]>([])
  // 当前高亮的角标编号。点正文角标或引用条目时更新。
  const [highlightedN, setHighlightedN] = useState<number | undefined>()

  // Next 16 的 params 是 Promise（见 next/dist/docs 的 metadata 示例）。
  // 用 `use()` 解包——它能在 Client Component 里同步取值，而 `await params`
  // 会让整个组件变成 async（Client Component 不允许）。
  const { id } = use(params)
  const reportId = Number(id)
  const idValid = Number.isInteger(reportId) && reportId > 0

  useEffect(() => {
    if (!idValid) return
    const controller = new AbortController()

    void (async () => {
      try {
        const report = await fetchReport(reportId, controller.signal)
        setResult({ kind: 'ready', report, loadedFor: reportId })
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setResult({
          kind: 'error',
          message: err instanceof Error ? err.message : '加载失败',
          loadedFor: reportId,
        })
      }
    })()

    return () => controller.abort()
  }, [reportId, idValid])

  // 「我的其它报告」：排除当前这篇。失败就空着——它是侧栏锦上添花，
  // 拉不到不该让整页报错。
  useEffect(() => {
    if (!idValid) return
    const controller = new AbortController()
    void (async () => {
      try {
        const list = await fetchReports({ limit: 6 }, controller.signal)
        setOthers(list.items.filter((r) => r.id !== reportId))
      } catch {
        setOthers([])
      }
    })()
    return () => controller.abort()
  }, [reportId, idValid])

  const handleCitationClick = useCallback((n: number) => {
    setHighlightedN(n)
  }, [])

  const handleCopyMarkdown = useCallback(() => {
    if (result?.kind !== 'ready') return
    void navigator.clipboard?.writeText(result.report.content)
  }, [result])

  if (!idValid) {
    return (
      <div className={styles.body}>
        <p role="alert" className={styles.stateError}>
          报告编号无效
        </p>
      </div>
    )
  }

  // 加载中：还没结果，或结果是另一个 id 的。
  if (!result || result.loadedFor !== reportId) {
    return (
      <div className={styles.body}>
        <p className={styles.stateText}>正在加载报告…</p>
      </div>
    )
  }

  if (result.kind === 'error') {
    return (
      <div className={styles.body}>
        <p role="alert" className={styles.stateError}>
          报告加载失败：{result.message}
        </p>
      </div>
    )
  }

  const { report } = result

  return (
    <div className={styles.body}>
      <ReportHeader
        reportId={report.id}
        question={report.question}
        onCopyMarkdown={handleCopyMarkdown}
      />
      <TitleHero
        question={report.question}
        createdAt={report.created_at}
        inputTokens={report.input_tokens}
        outputTokens={report.output_tokens}
        elapsedMs={report.elapsed_ms}
        citationCount={report.citations.length}
      />

      <div className={styles.grid}>
        <div className={styles.mainCol}>
          <ChapterSection
            content={report.content}
            citations={report.citations}
            onCitationClick={handleCitationClick}
          />
        </div>
        <aside className={styles.drawer}>
          <SourcesPanel
            citations={report.citations}
            totalCount={report.citations.length}
            highlightedN={highlightedN}
            onSelect={(c) => setHighlightedN(c.n)}
          />
          <RelatedReports reports={others} />
        </aside>
      </div>

      <ResearchDock question={report.question} />
    </div>
  )
}
