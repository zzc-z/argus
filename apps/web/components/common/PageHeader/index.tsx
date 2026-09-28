'use client'

import Link from 'next/link'
import { cn } from '@/lib/utils'
import { IconSpan } from '@/components/common/IconSpan'
import type {
  PageHeaderAction,
  PageHeaderBreadcrumb,
  PageHeaderConfig,
  PageHeaderEyebrow,
  PageHeaderMetaItem,
  PageHeaderStat,
} from './types'
import styles from './index.module.css'

export type {
  PageHeaderAction,
  PageHeaderActionVariant,
  PageHeaderBreadcrumb,
  PageHeaderConfig,
  PageHeaderEyebrow,
  PageHeaderMetaItem,
  PageHeaderStat,
} from './types'

function Crumb({ item }: { item: PageHeaderBreadcrumb }) {
  if (item.current || !item.href) {
    return (
      <span className={styles.breadcrumbItem}>
        {item.icon ? <IconSpan name={item.icon} size={14} /> : null}
        <span className={styles.breadcrumbCurrent} title={item.label}>
          {item.label}
        </span>
      </span>
    )
  }
  return (
    <span className={styles.breadcrumbItem}>
      {item.icon ? <IconSpan name={item.icon} size={14} /> : null}
      <Link href={item.href} className={styles.breadcrumbLink}>
        {item.label}
      </Link>
    </span>
  )
}

function Action({
  action,
  primaryLabelClass,
  shortcutClass,
}: {
  action: PageHeaderAction
  primaryLabelClass: string
  shortcutClass: string
}) {
  const variant = action.variant ?? 'secondary'
  const isIconOnly = !action.label && !!action.icon
  const variantClass = isIconOnly
    ? styles.iconOnly
    : variant === 'primary'
      ? styles.actionPrimary
      : variant === 'ghost'
        ? styles.actionGhost
        : variant === 'danger'
          ? styles.actionDanger
          : styles.actionSecondary
  const content = (
    <>
      {action.icon ? <IconSpan name={action.icon} size={isIconOnly ? 20 : 18} /> : null}
      {action.label ? (
        <span className={styles.actionLabel}>{action.label}</span>
      ) : null}
      {action.shortcut ? (
        <kbd
          className={cn(
            variant === 'primary' ? styles.shortcut : styles.shortcutSecondary,
            action.shortcutTone === 'dark' && variant === 'primary' && styles.shortcutDark,
          )}
        >
          {action.shortcut}
        </kbd>
      ) : null}
      {action.badge ? <span className={styles.badgeDot} /> : null}
      {action.badgeCount !== undefined && action.badgeCount > 0 ? (
        <span className={styles.badgeCount}>{action.badgeCount}</span>
      ) : null}
    </>
  )

  const className = cn(styles.action, variantClass, primaryLabelClass, action.className)
  const aria = action.ariaLabel ?? action.label ?? action.icon

  if (action.href) {
    return (
      <Link href={action.href} className={className} aria-label={aria}>
        {content}
      </Link>
    )
  }
  return (
    <button
      type="button"
      onClick={action.onClick}
      disabled={action.disabled}
      className={className}
      aria-label={aria}
    >
      {content}
    </button>
  )
}

/**
 * PageHeader — page-level title block shared across all dashboard pages.
 *
 * Layout:
 *   ┌─ breadcrumb (optional) ──────────────────┐
 *   │                                          │
 *   │  Title  [enLabel chip]                   │  Actions
 *   │  subtitle / stats row                    │  (right)
 *   └──────────────────────────────────────────┘
 *
 * Tokens: title 24/32/600, chip 12/18/500, subtitle/stats 13/20 body-sm,
 *         action primary label 16/24/500 (headline-sm), secondary 13/500.
 *
 * @see ./types.ts for the full config shape.
 */
export function PageHeader({
  title,
  enLabel,
  breadcrumb,
  eyebrow,
  subtitle,
  stats,
  meta,
  actions,
  extra,
  className,
}: PageHeaderConfig) {
  return (
    <header className={cn(styles.root, className)}>
      <div className={styles.left}>
        {eyebrow && (eyebrow.tag || eyebrow.note) ? (
          <div className={styles.eyebrow}>
            {eyebrow.tag ? (
              <span className={styles.eyebrowTag}>{eyebrow.tag}</span>
            ) : null}
            {eyebrow.tag && eyebrow.note ? (
              <span className={styles.eyebrowSep}>·</span>
            ) : null}
            {eyebrow.note ? (
              <span className={styles.eyebrowNote}>{eyebrow.note}</span>
            ) : null}
          </div>
        ) : null}

        {breadcrumb && breadcrumb.length > 0 ? (
          <nav className={styles.breadcrumb} aria-label="breadcrumb">
            {breadcrumb.map((item, i) => (
              <span key={`${item.label}-${i}`} className={styles.breadcrumbItem}>
                <Crumb item={item} />
                {i < breadcrumb.length - 1 ? (
                  <span className={styles.breadcrumbSep}>/</span>
                ) : null}
              </span>
            ))}
          </nav>
        ) : null}

        <div className={styles.titleRow}>
          <h1 className={styles.title}>{title}</h1>
          {enLabel ? <span className={styles.titleChip}>{enLabel}</span> : null}
        </div>

        {subtitle ? <p className={styles.subtitle}>{subtitle}</p> : null}

        {stats && stats.length > 0 ? (
          <div className={styles.stats}>
            {stats.map((stat, i) => {
              if (stat.pill) {
                return (
                  <span key={`pill-${i}`} className={styles.statPill}>
                    <span
                      className={cn(
                        styles.statPillDot,
                        stat.pillTone === 'success' && styles.statPillDotSuccess,
                      )}
                    />
                    {stat.value !== undefined ? <span>{stat.value}</span> : null}
                    <span>{stat.label}</span>
                  </span>
                )
              }
              return (
                <span key={`${stat.label}-${i}`} className={styles.breadcrumbItem}>
                  {stat.value !== undefined ? (
                    <span
                      className={cn(
                        styles.statValue,
                        stat.tone === 'highlight' && styles.statValueHighlight,
                      )}
                    >
                      {stat.value}
                    </span>
                  ) : null}
                  <span>{stat.label}</span>
                  {i < stats.length - 1 ? <span className={styles.statSep}>·</span> : null}
                </span>
              )
            })}
          </div>
        ) : null}

        {meta && meta.length > 0 ? (
          <div className={styles.meta}>
            {meta.map((item, i) => (
              <span key={`meta-${i}`} className={cn(styles.metaItem, item.className)}>
                {item.dot ? (
                  <span
                    className={cn(
                      styles.statPillDot,
                      item.dot === 'success' && styles.statPillDotSuccess,
                    )}
                  />
                ) : null}
                <span className={item.mono ? styles.metaItemMono : undefined}>{item.text}</span>
                {i < meta.length - 1 ? <span className={styles.metaSep}>/</span> : null}
              </span>
            ))}
          </div>
        ) : null}
      </div>

      {(actions && actions.length > 0) || extra ? (
        <div className={styles.right}>
          {extra}
          {actions?.map((action, i) => (
            <Action
              key={`${action.label ?? action.icon ?? 'action'}-${i}`}
              action={action}
              primaryLabelClass=""
              shortcutClass=""
            />
          ))}
        </div>
      ) : null}
    </header>
  )
}
