/**
 * PageHeader — page-level title + chip + subtitle/stats + actions block.
 * Tokens live in globals.css (`--text-*` / `--token-*`). All values here are
 * token refs so any change ripples consistently.
 */

import type { ReactNode } from 'react'
import type { Route } from 'next'

export type PageHeaderActionVariant = 'primary' | 'secondary' | 'ghost' | 'danger'

export interface PageHeaderAction {
  /** Material Symbols name. */
  icon?: string
  /** Visible label. Icon-only button when omitted. */
  label?: string
  /** Anchor href — renders as <Link>. Takes precedence over onClick. */
  href?: Route
  /** Button click handler. Ignored when href is set. */
  onClick?: () => void
  /** Style variant — drives bg / text / weight. Default: secondary. */
  variant?: PageHeaderActionVariant
  /** Keyboard shortcut chip rendered after the label (e.g. ⌘N). */
  shortcut?: string
  /** Shortcut chip bg: 'light' (white overlay on primary) or 'dark' (black overlay). */
  shortcutTone?: 'light' | 'dark'
  /** Small purple dot overlay (right-top of button). */
  badge?: boolean
  /** Numeric badge text overlay (e.g. notification count). */
  badgeCount?: number
  /** Disabled state. */
  disabled?: boolean
  /** Extra class names (escape hatch for one-off layout tweaks). */
  className?: string
  /** Aria label override (defaults to label or icon name). */
  ariaLabel?: string
}

export interface PageHeaderStat {
  /** Plain text label. */
  label: string
  /** Optional emphasised number/string rendered mono 600. */
  value?: string | number
  /** 'highlight' tints value with primary color; default = on-surface black. */
  tone?: 'default' | 'highlight'
  /** When true, render as a mono pill with leading pulse dot. */
  pill?: boolean
  /** Pill dot color when pill=true: 'primary' (purple) or 'success' (green). */
  pillTone?: 'primary' | 'success'
}

export interface PageHeaderBreadcrumb {
  /** Visible label. */
  label: string
  /** Optional href — renders as anchor. */
  href?: Route
  /** Optional leading icon. */
  icon?: string
  /** Marks current page (renders as plain text, no link). */
  current?: boolean
}

export interface PageHeaderEyebrow {
  /** Tag chip (rendered as mono code-style chip on surface-container-high). */
  tag?: string
  /** Plain note rendered after the tag, separated by '·'. */
  note?: string
}

export interface PageHeaderMetaItem {
  /** Text content. */
  text: string
  /** Mono emphasis (bold + mono font). Default = regular sans. */
  mono?: boolean
  /** Custom className for fine-grained color overrides. */
  className?: string
  /** Optional leading pulse dot (status indicator). */
  dot?: 'primary' | 'success'
}

export interface PageHeaderConfig {
  /** Page title (headline-lg 24/32/600). */
  title: string
  /** Optional English / product code chip rendered right of title. */
  enLabel?: string
  /** Optional breadcrumb row above the title block. */
  breadcrumb?: PageHeaderBreadcrumb[]
  /** Optional eyebrow tag + note rendered above the title (e.g. "AGENT WORKSPACE"). */
  eyebrow?: PageHeaderEyebrow
  /**
   * Subtitle / stats / meta row below the title.
   * - `subtitle` = single string → rendered as plain body-sm paragraph.
   * - `stats` = array → rendered as a flex row of mono-emphasised numbers.
   * - `meta` = array → rendered as flex row with mixed mono/sans + status dots
   *   (e.g. dashboard greeting + date + status block).
   */
  subtitle?: string
  stats?: PageHeaderStat[]
  meta?: PageHeaderMetaItem[]
  /** Right-side actions. Up to ~4 supported; collapses on small screens. */
  actions?: PageHeaderAction[]
  /** Optional custom DOM node rendered after actions (e.g. live status pill). */
  extra?: ReactNode
  /** Extra class names for the <header> root. */
  className?: string
}
