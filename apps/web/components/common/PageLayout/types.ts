import type { ReactNode } from 'react'
import type { PageHeaderConfig } from '@/components/common/PageHeader/types'

export interface PageLayoutProps {
  /**
   * Page-level header config. Rendered by the shared PageHeader component.
   * If omitted, no header is rendered.
   */
  header?: PageHeaderConfig
  /** Page body content (tables, charts, cards, etc.). */
  children?: ReactNode
  /** Extra class names for the outer wrapper. */
  className?: string
}
