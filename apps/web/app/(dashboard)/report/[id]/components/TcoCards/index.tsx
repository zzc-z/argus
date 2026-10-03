'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import { cn } from '@/lib/utils'
import { type TcoCard, tcoCallout } from '../../mock'
import styles from './index.module.css'

export interface TcoCardsProps {
  cards: TcoCard[]
}

/**
 * SECTION 04 — three TCO stat cards + Architect Recommendation callout.
 * Pure presentation.
 */
export function TcoCards({ cards }: TcoCardsProps) {
  return (
    <>
      <div className={styles.grid}>
        {cards.map((c) => (
          <div key={c.id} className={styles.card}>
            <span className={cn(styles.label, 'font-label-sm')}>{c.label}</span>
            <div className={styles.valueRow}>
              <span className={cn(styles.value, 'font-headline-xl')}>{c.value}</span>
              <span
                className={cn(
                  styles.badge,
                  'font-code',
                  c.badgeTone === 'success' && styles.badgeSuccess,
                  c.badgeTone === 'primary' && styles.badgePrimary,
                  c.badgeTone === 'muted' && styles.badgeMuted,
                )}
              >
                {c.badge}
              </span>
            </div>
            <span className={cn(styles.caption, 'font-body-sm')}>{c.caption}</span>
          </div>
        ))}
      </div>

      <div className={styles.callout}>
        <div className={cn(styles.calloutHead, 'font-headline-sm')}>
          <IconSpan name="verified_user" size={18} className="text-primary" />
          <span>{tcoCallout.headline}</span>
        </div>
        <p className={cn(styles.calloutBody, 'font-body-md')}>{tcoCallout.body}</p>
      </div>
    </>
  )
}
