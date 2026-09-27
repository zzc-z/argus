import * as React from 'react'
import styles from './index.module.css'

export interface ErrorDisplayProps {
  title: string
  subtitle: string
}

/**
 * Massive typographic "404 / 500" gradient block + headline + subtitle.
 * Pure server component — no state.
 */
export function ErrorDisplay({ title, subtitle }: ErrorDisplayProps) {
  return (
    <section className={styles.section}>
      <div className={styles.codeRow}>
        <span
          className={`${styles.codeLeft} from-primary-container via-primary to-outline-variant font-code bg-gradient-to-r bg-clip-text font-bold tracking-tighter text-transparent`}
        >
          404
        </span>
        <span className={`${styles.codeSlash} font-code text-outline mx-2 font-light`}>/</span>
        <span
          className={`${styles.codeRight} from-outline to-on-surface-variant font-code bg-gradient-to-r bg-clip-text font-bold tracking-tighter text-transparent opacity-80`}
        >
          500
        </span>
      </div>

      <h1
        className={`${styles.title} sm:font-headline-xl font-headline-lg text-on-surface tracking-tight`}
      >
        {title}
      </h1>

      <p className={`${styles.subtitle} font-body-md text-secondary leading-relaxed`}>{subtitle}</p>
    </section>
  )
}
