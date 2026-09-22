import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import type { ExploreReport } from "../../mock";
import styles from "./index.module.css";

export interface ExploreGridProps {
  reports: ExploreReport[];
}

/**
 * "Continue your research" 3-column grid of report cards.
 * Each card: cover (icon + tag chips) + title + stats row + CTA.
 */
export function ExploreGrid({ reports }: ExploreGridProps) {
  return (
    <section className={styles.root}>
      <header className={styles.head}>
        <div className={styles.headTitle}>
          <IconSpan name="auto_stories" size={18} className="text-primary-container" />
          <h2 className={`${styles.title} font-headline-sm font-semibold tracking-tight`}>
            继续您的研究探索
          </h2>
        </div>
        <a href="#" className={`${styles.browseAll} font-label-sm font-medium`}>
          前往深度研报库
          <IconSpan name="arrow_forward" size={14} />
        </a>
      </header>

      <div className={styles.grid}>
        {reports.map((r) => (
          <article key={r.id} className={styles.card}>
            <div className={styles.cover}>
              <IconSpan name={r.coverIcon} size={24} className="text-primary-container" />
              <div className={styles.tags}>
                {r.tags.map((t) => (
                  <span key={t} className={`${styles.tag} font-label-sm font-medium`}>
                    {t}
                  </span>
                ))}
              </div>
            </div>

            <div className={styles.body}>
              <h3 className={`${styles.cardTitle} font-body-md font-semibold`}>
                {r.title}
              </h3>

              <div className={styles.statsRow}>
                <span className={`${styles.stat} font-label-sm`}>
                  <IconSpan name="schedule" size={13} />
                  {r.activity}
                </span>
                <span className={`${styles.stat} font-label-sm`}>
                  <IconSpan name="group" size={13} />
                  {r.agents} 智能体协作
                </span>
                <span className={`${styles.stat} font-label-sm`}>
                  <IconSpan name="link" size={13} />
                  {r.citations} 引用
                </span>
              </div>

              <p className={`${styles.footer} font-label-sm`}>{r.footer}</p>

              <button
                type="button"
                className={
                  r.ctaPrimary
                    ? `${styles.cta} ${styles.ctaPrimary} font-body-sm font-medium`
                    : `${styles.cta} ${styles.ctaSecondary} font-body-sm font-medium`
                }
              >
                {r.ctaLabel}
                <IconSpan name="arrow_forward" size={14} />
              </button>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}