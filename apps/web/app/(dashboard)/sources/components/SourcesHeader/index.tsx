'use client'

import * as React from 'react'
import Link from 'next/link'
import { IconSpan } from '@/components/common/IconSpan'
import { sourceStats } from '../../mock'
import styles from './index.module.css'

/**
 * Top command & header tier — title + stats + bulk reindex + upload CTA.
 * The upload CTA is a Next.js `Link` to /add-sources (cross-page navigation).
 */
export function SourcesHeader() {
  return (
    <header className={styles.header}>
      <div className={styles.titleBlock}>
        <div className={styles.titleRow}>
          <span className={`${styles.title} font-headline-lg font-semibold tracking-tight`}>
            资料库 (Source Library)
          </span>
          <span className={`${styles.chip} font-code`}>RAG Vector Hub</span>
        </div>
        <div className={`${styles.stats} font-body-sm`}>
          <span>已索引</span>
          <span className={`${styles.statNumber} font-code`}>{sourceStats.total}</span>
          <span>个数据源</span>
          <span className={styles.dot}>·</span>
          <span className={`${styles.statHighlight} font-code`}>{sourceStats.totalSize}</span>
          <span>向量化知识图谱与切片 (Embedding Core)</span>
        </div>
      </div>

      <div className={styles.actions}>
        <button type="button" className={`${styles.reindexBtn} font-headline-sm`}>
          <IconSpan name="sync" size={18} className={`${styles.syncIcon} text-secondary`} />
          <span className="text-[13px]">批量重新索引</span>
        </button>
        <Link href="/add-sources" className={`${styles.uploadBtn} font-headline-sm`}>
          <IconSpan name="add_circle" size={18} />
          <span className="text-[13px] font-medium">+ 上传新资料</span>
        </Link>
      </div>
    </header>
  )
}
