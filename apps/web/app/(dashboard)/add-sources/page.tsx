'use client'

/**
 * Add Sources page — upload / URL / RSS ingestion + processing pipeline options.
 *
 * Two-column layout:
 *   - Left (7/12):  UploadDropZone + UrlRssTabs + ProcessingOptions + arch badge
 *   - Right (5/12): QueueMonitor (4 tasks) + security tip card
 *
 * URL/RSS tab state is local (useState); queue items are static mock.
 */

import * as React from 'react'
import { useState } from 'react'
import Link from 'next/link'

import { AddSourcesHeader } from './components/AddSourcesHeader'
import { UploadDropZone } from './components/UploadDropZone'
import { UrlRssTabs } from './components/UrlRssTabs'
import { ProcessingOptions } from './components/ProcessingOptions'
import { QueueMonitor } from './components/QueueMonitor'
import { IconSpan } from '@/components/common/IconSpan'

import styles from './page.module.css'

type IngestTab = 'url' | 'rss'

export default function AddSourcesPage() {
  const [tab, setTab] = useState<IngestTab>('url')

  return (
    <main className={styles.main}>
      <div className={styles.body}>
        <AddSourcesHeader />

        <div className={styles.grid}>
          {/* LEFT — ingestion inputs */}
          <div className={styles.left}>
            <UploadDropZone />
            <UrlRssTabs tab={tab} onTabChange={setTab} />
            <ProcessingOptions />
            <ArchBadge />
          </div>

          {/* RIGHT — ingestion queue */}
          <div className={styles.right}>
            <QueueMonitor />
            <SecurityTip />
            <BackLink />
          </div>
        </div>
      </div>
    </main>
  )
}

/** Compact one-line badge — HNSW dense + sparse BM25 fusion engine. */
function ArchBadge() {
  return (
    <div className={styles.arch}>
      <div className={styles.archInner}>
        <div className={styles.archIcon}>
          <IconSpan name="account_tree" size={20} className="text-primary-container" />
        </div>
        <div>
          <span className={`${styles.archTitle} font-body-sm`}>双层拓扑向量索引模式已就绪</span>
          <span className={`${styles.archMeta} font-label-sm`}>
            HNSW Dense Index (1536d) + Sparse BM25 Fusion Engine
          </span>
        </div>
      </div>
      <div className={styles.archRight}>
        <span className={`${styles.archQps} font-code`}>QPS: 124.8</span>
        <span className={styles.archLive} />
      </div>
    </div>
  )
}

/** Compact security / compliance tip card. */
function SecurityTip() {
  return (
    <section className={styles.tip}>
      <div className={styles.tipHead}>
        <IconSpan name="info" size={18} className="text-primary-container" />
        <span className={`${styles.tipTitle} font-headline-sm`}>知识索引准则</span>
      </div>
      <p className={`${styles.tipBody} font-body-sm`}>
        所有非结构化文献将通过本地隔离沙箱进行消毒与语义切片。敏感数据自动脱敏,生成出的向量索引将实时绑定至对应工作区专有推演图谱,不参与通用基础模型再训练。
      </p>
    </section>
  )
}

/** Back link to /sources — quick return CTA for power users. */
function BackLink() {
  return (
    <Link href="/sources" className={`${styles.backLink} font-body-sm`}>
      <IconSpan name="arrow_back" size={16} />
      <span>返回资料库</span>
    </Link>
  )
}
