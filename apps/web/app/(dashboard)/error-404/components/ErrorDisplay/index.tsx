import * as React from "react";
import styles from "./index.module.css";

export interface ErrorDisplayProps {
  title: string;
  subtitle: string;
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
          className={`${styles.codeLeft} font-code font-bold text-transparent bg-clip-text bg-gradient-to-r from-primary-container via-primary to-outline-variant tracking-tighter`}
        >
          404
        </span>
        <span className={`${styles.codeSlash} font-code font-light text-outline mx-2`}>
          /
        </span>
        <span
          className={`${styles.codeRight} font-code font-bold text-transparent bg-clip-text bg-gradient-to-r from-outline to-on-surface-variant tracking-tighter opacity-80`}
        >
          500
        </span>
      </div>

      <h1
        className={`${styles.title} font-headline-lg sm:font-headline-xl text-on-surface tracking-tight`}
      >
        {title}
      </h1>

      <p className={`${styles.subtitle} font-body-md text-secondary leading-relaxed`}>
        {subtitle}
      </p>
    </section>
  );
}
