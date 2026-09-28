'use client'

import * as React from 'react'
import { useState } from 'react'
import Link from 'next/link'

import { PageLayout } from '@/components/common/PageLayout'
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
          <UploadDropZone />
          <UrlRssTabs tab={tab} onTabChange={setTab} />
          <ProcessingOptions />
          <ArchBadge />
        </div>

        <div className={styles.right}>
          <QueueMonitor />
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
