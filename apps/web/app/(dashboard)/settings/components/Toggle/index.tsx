'use client'

import * as React from 'react'
import { cn } from '@/lib/utils'
import styles from './index.module.css'

export type ToggleSize = 'lg' | 'md' | 'sm'

export interface ToggleProps {
  checked: boolean
  onChange: (next: boolean) => void
  size?: ToggleSize
  ariaLabel?: string
  disabled?: boolean
}

/**
 * Pure toggle switch. Three sizes mirror the design (lg = master, md = sub-toggle, sm = rule card).
 * The track is a peer-controlled div that swaps `surface-container-high` → `primary-container`
 * via the `data-on` attribute — no Tailwind arbitrary values needed.
 */
export function Toggle({
  checked,
  onChange,
  size = 'lg',
  ariaLabel,
  disabled = false,
}: ToggleProps) {
  const sizeClass = size === 'lg' ? styles.lg : size === 'md' ? styles.md : styles.sm
  return (
    <label className={cn(styles.wrap, disabled && styles.disabled)} data-on={checked || undefined}>
      <input
        type="checkbox"
        className={styles.input}
        checked={checked}
        disabled={disabled}
        aria-label={ariaLabel}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className={cn(styles.track, sizeClass)} />
    </label>
  )
}
