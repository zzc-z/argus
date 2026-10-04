'use client'

import * as React from 'react'
import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'

import { PageLayout } from '@/components/common/PageLayout'
import { UploadDropZone } from './components/UploadDropZone'
import { UrlRssTabs } from './components/UrlRssTabs'
import { ProcessingOptions } from './components/ProcessingOptions'
import { QueueMonitor } from './components/QueueMonitor'
import { IconSpan } from '@/components/common/IconSpan'

import { queueItems as initialQueueItems, type QueueItem } from './mock'

import styles from './page.module.css'

type IngestTab = 'url' | 'rss'

/** Stable counter for synthetic QueueItem IDs created by user actions. */
let queueIdCounter = 0
const nextQueueId = (prefix: string) => `${prefix}-${Date.now()}-${queueIdCounter++}`

export default function AddSourcesPage() {
  const [tab, setTab] = useState<IngestTab>('url')
  const [queueItems, setQueueItems] = useState<QueueItem[]>(initialQueueItems)
  const timersRef = useRef<Map<string, ReturnType<typeof setInterval>>>(new Map())

  /** Advance a single item's progress every 1s until 100, then mark done. */
  const startProgressTimer = (id: string) => {
    const timer = setInterval(() => {
      setQueueItems((prev) =>
        prev.map((it) => {
          if (it.id !== id || it.done) return it
          const next = Math.min(100, it.progress + 5)
          if (next >= 100) {
            return {
              ...it,
              progress: 100,
              done: true,
              timing: '100%',
              entities: '已注入概念图谱',
              statusLabel: '已索引至向量数据库',
              progressLabel: `${next}/100 chunks`,
            }
          }
          return { ...it, progress: next, progressLabel: `${next}/100 chunks` }
        }),
      )
    }, 1000)
    timersRef.current.set(id, timer)
  }

  /** Clean up all running progress timers when the page unmounts. */
  useEffect(() => {
    const timers = timersRef.current
    return () => {
      timers.forEach((t) => clearInterval(t))
      timers.clear()
    }
  }, [])

  const handleFilesSelected = (files: File[]) => {
    const added: QueueItem[] = files.map((file) => ({
      id: nextQueueId('q-upload'),
      name: file.name,
      kindLabel: 'PDF',
      size: `${(file.size / 1024 / 1024).toFixed(1)} MB`,
      progress: 0,
      progressLabel: '0/100 chunks',
      statusLabel: '已加入处理队列,等待分配执行节点...',
      iconName: 'picture_as_pdf',
      iconAccent: 'errorContainer',
    }))
    setQueueItems((prev) => [...prev, ...added])
    added.forEach((it) => startProgressTimer(it.id))
  }

  const handleUrlSubmit = (url: string) => {
    const id = nextQueueId('q-url')
    const item: QueueItem = {
      id,
      name: url,
      kindLabel: 'Web HTML',
      size: '—',
      progress: 0,
      progressLabel: '0/100 chunks',
      statusLabel: '已加入处理队列,等待 Playwright 抓取调度...',
      iconName: 'html',
      iconAccent: 'surfaceHighest',
    }
    setQueueItems((prev) => [...prev, item])
    startProgressTimer(id)
  }

  const handleRssSubmit = (url: string, period: '1h' | '6h' | '24h') => {
    const id = nextQueueId('q-rss')
    const item: QueueItem = {
      id,
      name: url,
      kindLabel: 'RSS / Atom',
      size: period,
      progress: 0,
      progressLabel: '0/100 chunks',
      statusLabel: 'RSS 源已验证,正在生成语义向量图谱增量...',
      iconName: 'rss_feed',
      iconAccent: 'primaryFixed',
    }
    setQueueItems((prev) => [...prev, item])
    startProgressTimer(id)
  }

  return (
    <PageLayout
      header={{
        breadcrumb: [
          { label: '资料库', href: '/sources', icon: 'database' },
          { label: '添加新数据源', current: true },
        ],
        title: '添加研究资料 Add Sources',
        subtitle:
          '上传离线研究文档、输入网页链接或订阅专业 RSS 数据流以扩充 Argus 知识库与推演图谱',
        stats: [
          { label: 'INGEST_V2', pill: true, pillTone: 'primary' },
          { label: '端到端加密通道 · 零留存模式' },
        ],
      }}
    >
      <div className={styles.grid}>
        <div className={styles.left}>
          <UploadDropZone onFilesSelected={handleFilesSelected} />
          <UrlRssTabs
            tab={tab}
            onTabChange={setTab}
            onUrlSubmit={handleUrlSubmit}
            onRssSubmit={handleRssSubmit}
          />
          <ProcessingOptions />
          <ArchBadge />
        </div>

        <div className={styles.right}>
          <QueueMonitor items={queueItems} />
          <SecurityTip />
          <BackLink />
        </div>
      </div>
    </PageLayout>
  )
}

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

function BackLink() {
  return (
    <Link href="/sources" className={`${styles.backLink} font-body-sm`}>
      <IconSpan name="arrow_back" size={16} />
      <span>返回资料库</span>
    </Link>
  )
}
