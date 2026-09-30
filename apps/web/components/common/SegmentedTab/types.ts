/**
 * SegmentedTab — pill-style segmented control with optional count chip.
 *
 * Tokens live in globals.css (`--token-*` / `--text-*`). All values here are
 * token refs so any change ripples consistently across consumers (reports,
 * topics, sources, …).
 */

export interface SegmentedTabItem {
  /** Stable id — returned to onChange when the tab is clicked. */
  id: string
  /** Visible label. */
  label: string
  /** Optional count rendered as a purple mono chip. */
  count?: number
  /** Disabled by default. */
  disabled?: boolean
}

export interface SegmentedTabProps {
  items: SegmentedTabItem[]
  /** Currently active tab id. */
  activeId: string
  /** Called with the clicked tab id. */
  onChange: (id: string) => void
  /** Visual size — `md` (default) matches reports/topics, `sm` is for tight rows. */
  size?: 'sm' | 'md'
  /** Aria label for the underlying tablist. */
  ariaLabel?: string
  /** Extra class names for the root container. */
  className?: string
}