'use client'

import * as React from 'react'
import { PageLayout } from '@/components/common/PageLayout'
import { SourceFilterBar } from './components/SourceFilterBar'
import { SourceFilterSidebar } from './components/SourceFilterSidebar'
import { SourceBulkRibbon } from './components/SourceBulkRibbon'
import { SourceTable } from './components/SourceTable'
import { SourcePagination } from './components/SourcePagination'
import { sourceRows } from './mock'
import styles from './page.module.css'

export default function SourcesPage() {
  const [selectedIds, setSelectedIds] = React.useState<Set<string>>(new Set())

  const toggleRow = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleAll = () => {
    setSelectedIds((prev) => {
      if (prev.size === sourceRows.length) return new Set()
      return new Set(sourceRows.map((r) => r.id))
    })
  }

  const allChecked = selectedIds.size === sourceRows.length
  const indeterminate = selectedIds.size > 0 && selectedIds.size < sourceRows.length

  return (
    <PageLayout
      header={{
        title: '资料库 (Source Library)',
        enLabel: 'RAG Vector Hub',
        stats: [
          { label: '已索引', value: 847 },
          { label: '个数据源' },
          { label: '向量化知识图谱与切片 (Embedding Core)', value: '12.4 GB', tone: 'highlight' },
        ],
        actions: [
          { label: '批量重新索引', icon: 'sync', variant: 'secondary' },
          { label: '+ 上传新资料', icon: 'add_circle', variant: 'primary', href: '/add-sources' },
        ],
      }}
    >
      <SourceFilterBar />
      <div className={styles.workspace}>
        <SourceFilterSidebar />
        <div className={styles.stage}>
          <SourceBulkRibbon
            selectedCount={selectedIds.size}
            allChecked={allChecked}
            indeterminate={indeterminate}
            onToggleAll={toggleAll}
          />
          <SourceTable
            data={sourceRows}
            selection={{
              selectedIds,
              onToggle: toggleRow,
              onToggleAll: toggleAll,
              allSelected: allChecked,
              partiallySelected: indeterminate,
            }}
          />
          <SourcePagination />
        </div>
      </div>
    </PageLayout>
  )
}
