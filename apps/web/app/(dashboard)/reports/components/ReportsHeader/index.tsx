'use client'

import { PageHeader } from '@/components/common/PageHeader'
import {
  CTA_FILTER_LABEL,
  CTA_NEW_RESEARCH_LABEL,
  CTA_NEW_RESEARCH_SHORTCUT,
  PAGE_DAG_STATUS,
  PAGE_SUBTITLE_MID,
  PAGE_SUBTITLE_PREFIX,
  PAGE_SUBTITLE_REPORT_COUNT,
  PAGE_SUBTITLE_TRACK_COUNT,
  PAGE_SUBTITLE_TRACK_PREFIX,
  PAGE_SUBTITLE_TRACK_SUFFIX,
  PAGE_TITLE,
  PAGE_TITLE_EN,
} from '../../mock'

export interface ReportsHeaderProps {
  filterBadgeVisible: boolean
  onToggleFilters: () => void
  onNewResearch: () => void
}

/**
 * Reports page header — title + DAG Cluster chip + subtitle (with stats) +
 * multi-dimensional filter + new-research CTA. Action handlers owned by page.tsx.
 */
export function ReportsHeader({
  filterBadgeVisible,
  onToggleFilters,
  onNewResearch,
}: ReportsHeaderProps) {
  return (
    <PageHeader
      title={PAGE_TITLE}
      enLabel={PAGE_TITLE_EN}
      subtitle={`${PAGE_SUBTITLE_PREFIX} ${PAGE_SUBTITLE_REPORT_COUNT} ${PAGE_SUBTITLE_MID} · ${PAGE_SUBTITLE_TRACK_PREFIX} ${PAGE_SUBTITLE_TRACK_COUNT} ${PAGE_SUBTITLE_TRACK_SUFFIX} · ${PAGE_DAG_STATUS}`}
      actions={[
        {
          label: CTA_FILTER_LABEL,
          icon: 'tune',
          variant: 'secondary',
          badge: filterBadgeVisible,
          onClick: onToggleFilters,
        },
        {
          label: CTA_NEW_RESEARCH_LABEL,
          icon: 'add',
          variant: 'primary',
          shortcut: CTA_NEW_RESEARCH_SHORTCUT,
          onClick: onNewResearch,
        },
      ]}
    />
  )
}
