'use client'

/**
 * Sources (资料库) — source library list page.
 *
 * Layout: top command bar (title + stats + bulk reindex + upload CTA) +
 * filter & search sub-bar + two-column workspace (left filter sidebar +
 * right table). All data is local mock; row state is in-component.
 *
 * Page composition:
 *   - SourcesHeader       (title + "RAG Vector Hub" chip + reindex + upload Link)
 *   - SourceFilterBar     (category tabs + search + view switch + sort)
 *   - SourceFilterSidebar (type / status / timeline / tags / storage quota)
 *   - SourceBulkRibbon    (select-all + bulk actions, counts from page state)
 *   - SourceTable         (mock rows + row checkbox + status badges)
 *   - SourcePagination    (page numbers)
 */

import * as React from 'react'
import { useState } from 'react'

import { SourcesHeader } from './components/SourcesHeader'
import { SourceFilterBar } from './components/SourceFilterBar'
import { SourceFilterSidebar } from './components/SourceFilterSidebar'
import { SourceBulkRibbon } from './components/SourceBulkRibbon'
import { SourceTable } from './components/SourceTable'
import { SourcePagination } from './components/SourcePagination'

import { sourceRows } from './mock'
import styles from './page.module.css'

export default function SourcesPage() {
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())

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
    <div className={styles.body}>
      <SourcesHeader />

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
          <SourceTable selectedIds={selectedIds} onToggleRow={toggleRow} />
          <SourcePagination />
        </div>
      </div>
    </div>
  )
}
