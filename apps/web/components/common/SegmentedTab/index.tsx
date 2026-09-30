'use client'

import * as React from 'react'
import { cn } from '@/lib/utils'
import type { SegmentedTabProps } from './types'
import styles from './index.module.css'

export type { SegmentedTabItem, SegmentedTabProps } from './types'

/**
 * SegmentedTab — shared pill-style segmented control used by /reports,
 * /topics, /sources filter bars. Single source of truth for the
 * "tab + mono count chip" pattern.
 *
 * Visual: rounded-lg container on surface-container-low, active tab on
 * surface-container-lowest with a soft shadow, count chip rendered mono in
 * primary purple (active) or secondary grey (inactive).
 *
 * Tokens: container bg surface-container-low, active bg surface-container-lowest,
 *         label body-sm, count text-code.
 */
export function SegmentedTab({
  items,
  activeId,
  onChange,
  size = 'md',
  ariaLabel,
  className,
}: SegmentedTabProps) {
  const rootClass = cn(styles.root, size === 'sm' && styles.rootSm, className)

  return (
    <div className={rootClass} role="tablist" aria-label={ariaLabel}>
      {items.map((item) => {
        const active = item.id === activeId
        const tabClass = cn(
          styles.tab,
          size === 'sm' && styles.tabSm,
          active && styles.tabActive,
          item.disabled && styles.tabDisabled,
        )
        return (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={active}
            aria-disabled={item.disabled || undefined}
            disabled={item.disabled}
            className={tabClass}
            onClick={() => {
              if (!item.disabled) onChange(item.id)
            }}
          >
            <span className={styles.label}>{item.label}</span>
            {item.count !== undefined ? (
              <span
                className={cn(
                  styles.count,
                  active ? styles.countActive : styles.countInactive,
                )}
              >
                {item.count}
              </span>
            ) : null}
          </button>
        )
      })}
    </div>
  )
}