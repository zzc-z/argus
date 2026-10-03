'use client'

/**
 * Report detail page — `/report/[id]`.
 *
 * Layout (1:1 from argus_report_detail/code.html):
 *   ┌─ ReportHeader (breadcrumb + share/export/... actions)
 *   ├─ Title hero (full-width)
 *   ├─ View switcher (4 tabs: report / comparison / timeline / decision)
 *   ├─ Active view body — each view owns a 12-col grid (xl:8 main + xl:4 drawer)
 *   │    └─ Right drawer — SourcesPanel + (report-only) AgentLogPanel + RelatedReports
 *   └─ ResearchDock (fixed bottom, floating)
 *
 * Interaction state owned here:
 *   - active view tab (4 tabs, all wired)
 *   - highlighted source id (click a citation mark → highlight source row)
 *   - comparison scope (H100 / B200 / Rack)
 *
 * Note: layout.tsx in `(dashboard)` owns the sidebar + top header chrome.
 */

import * as React from 'react'
import { useMemo, useState } from 'react'

import { TitleHero } from './components/TitleHero'
import { ViewSwitcher } from './components/ViewSwitcher'
import { ReportHeader } from './components/ReportHeader'
import { ChapterSection } from './components/ChapterSection'
import { SpecTable } from './components/SpecTable'
import { BenchmarkBars } from './components/BenchmarkBars'
import { TcoCards } from './components/TcoCards'
import { SourcesPanel } from './components/SourcesPanel'
import { AgentLogPanel } from './components/AgentLogPanel'
import { RelatedReports } from './components/RelatedReports'
import { ResearchDock } from './components/ResearchDock'

import { ComparisonTabs } from './components/ComparisonTabs'
import { TimelineTrack } from './components/TimelineTrack'
import { DecisionList } from './components/DecisionList'

import {
  agents,
  benchmarks,
  chapter1,
  citations,
  decisionItems,
  relatedReports,
  sources,
  specRows,
  tcoCards,
  timelineEvents,
  type ViewKey,
} from './mock'

import styles from './page.module.css'

export default function ReportPage({ params }: { params: { id: string } }) {
  // 当前 mock：声明所有 id 都映射到同一份详情。后续接 API 时改成按 id 选 mock。
  void params

  const [activeView, setActiveView] = useState<ViewKey>('report')
  const [highlightedSourceId, setHighlightedSourceId] = useState<string | undefined>()

  // Citation id → surface label ("1"…"4"). Used by ChapterSection to render
  // the inline superscript marks at the end of a paragraph.
  const citationSurfaceMap = useMemo(() => {
    const map = new Map<string, string>()
    for (const c of citations) map.set(c.id, c.surface)
    return map
  }, [])

  // Highlighted source id is derived from a citation click. Look up the
  // source that owns this citation (1:1 by indexLabel stripping brackets).
  const handleCitationClick = (citationId: string) => {
    const surface = citationSurfaceMap.get(citationId)
    if (!surface) return
    const src = sources.find((s) => s.indexLabel === `[${surface}]`)
    if (src) setHighlightedSourceId(src.id)
  }

  // Right drawer — SourcesPanel + RelatedReports always shown; AgentLogPanel
  // only on the long-form report view.
  const drawer = (
    <aside className={styles.drawer}>
      <SourcesPanel sources={sources} totalCount={23} highlightedId={highlightedSourceId} />
      {activeView === 'report' && <AgentLogPanel agents={agents} />}
      <RelatedReports reports={relatedReports} />
    </aside>
  )

  return (
    <div className={styles.body}>
      <ReportHeader />
      <TitleHero />
      <ViewSwitcher value={activeView} onChange={setActiveView} />

      {activeView === 'report' && (
        <div className={styles.grid}>
          <div className={styles.mainCol}>
            <ChapterSection
              chapter={chapter1}
              citationSurface={(id: string) => citationSurfaceMap.get(id)}
              onCitationClick={handleCitationClick}
            />

            <ChapterSection
              chapter={{
                id: 'ch-2-spec',
                number: '02',
                title: '微架构横向演进关键数据',
                meta: '标称规格矩阵对比',
                blocks: [
                  {
                    kind: 'p',
                    text: '下表罗列了单卡 H100 SXM、B200 Tensor Core GPU 与整机架交付的 GB200 NVL72 平台在关键硬件维度的技术指标演进比对：',
                  },
                ],
              }}
              citationSurface={(id: string) => citationSurfaceMap.get(id)}
              onCitationClick={handleCitationClick}
            >
              <SpecTable rows={specRows} />
            </ChapterSection>

            <ChapterSection
              chapter={{
                id: 'ch-3-bench',
                number: '03',
                title: '推理性能基准与吞吐量评测',
                meta: 'Llama 3 70B · Mixtral 8x22B',
                blocks: [
                  {
                    kind: 'p',
                    text: '针对目前工业界最常用的两个开源基准模型 —— Llama 3 70B (Dense) 与 Mixtral 8x22B (Sparse MoE)，在并发批处理（Batch Size = 128 / 256）下的单卡/节点等效吞吐量（Tokens/sec/GPU）测算：',
                  },
                ],
              }}
              citationSurface={(id: string) => citationSurfaceMap.get(id)}
              onCitationClick={handleCitationClick}
            >
              <BenchmarkBars cards={benchmarks} />
            </ChapterSection>

            <ChapterSection
              chapter={{
                id: 'ch-4-tco',
                number: '04',
                title: 'TCO 综合拥有成本模型拆解',
                meta: '3年生命周期折算',
                blocks: [
                  {
                    kind: 'p',
                    text: '很多采购决策者误以为 Blackwell 单卡功耗攀升至 1000W+、GB200 NVL72 机架高达 120kW 会极大增加机房运营开支。但按照「每百万 Token 推理总持有成本 (TCO per 1M Tokens)」进行全口径折算，结果却呈现截然相反的成本曲线。',
                    citationIds: ['4'],
                  },
                ],
              }}
              citationSurface={(id: string) => citationSurfaceMap.get(id)}
              onCitationClick={handleCitationClick}
            >
              <TcoCards cards={tcoCards} />
            </ChapterSection>
          </div>
          {drawer}
        </div>
      )}

      {activeView === 'comparison' && (
        <div className={styles.grid}>
          <div className={styles.mainCol}>
            <ComparisonTabs specRows={specRows} benchmarks={benchmarks} />
          </div>
          {drawer}
        </div>
      )}

      {activeView === 'timeline' && (
        <div className={styles.grid}>
          <div className={styles.mainCol}>
            <TimelineTrack events={timelineEvents} />
          </div>
          {drawer}
        </div>
      )}

      {activeView === 'decision' && (
        <div className={styles.grid}>
          <div className={styles.mainCol}>
            <DecisionList items={decisionItems} tcoCards={tcoCards} />
          </div>
          {drawer}
        </div>
      )}

      <ResearchDock />
    </div>
  )
}