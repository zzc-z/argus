'use client'

import { PageHeader } from '@/components/common/PageHeader'
import { sourceStats } from '../../mock'

/**
 * Sources page header — title + RAG Vector Hub chip + stats row + reindex / upload CTAs.
 * The upload CTA is a Next.js `Link` to /add-sources (cross-page navigation).
 */
export function SourcesHeader() {
  return (
    <PageHeader
      title="资料库 (Source Library)"
      enLabel="RAG Vector Hub"
      stats={[
        { label: '已索引', value: sourceStats.total },
        { label: '个数据源' },
        { label: '向量化知识图谱与切片 (Embedding Core)', value: sourceStats.totalSize, tone: 'highlight' },
      ]}
      actions={[
        {
          label: '批量重新索引',
          icon: 'sync',
          variant: 'secondary',
        },
        {
          label: '+ 上传新资料',
          icon: 'add_circle',
          variant: 'primary',
          href: '/add-sources',
        },
      ]}
    />
  )
}
