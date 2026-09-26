/**
 * ExploreGrid — 1:1 with argus_dashboard/code.html "继续您的研究探索" row.
 *
 * Each card:
 *   - cover with background-image (URL) + dark gradient overlay
 *   - 2 dark tags bottom-left + dark timestamp top-right
 *   - title (truncate 2 lines) + citation stats row
 *   - footer: progress label + primary/secondary CTA
 */

import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import { cn } from "@/lib/utils";
import type { ExploreReport } from "../../mock";
import styles from "./index.module.css";

export interface ExploreGridProps {
  reports: ExploreReport[];
}

export function ExploreGrid({ reports }: ExploreGridProps) {
  return (
    <section className={styles.root}>
      <header className={styles.head}>
        <div className={styles.headTitle}>
          <IconSpan name="explore" size={20} className={styles.headIcon} />
          <h2
            className={`${styles.title} font-headline-md font-semibold tracking-tight`}
          >
            继续您的研究探索
          </h2>
        </div>
        <span className={`${styles.headMeta} font-body-sm`}>
          最近更新与上下文命中
        </span>
      </header>

      <div className={styles.grid}>
        {reports.map((r) => (
          <article key={r.id} className={styles.card}>
            <div>
              <div className={styles.cover}>
                <div
                  className={styles.coverImage}
                  style={{ backgroundImage: `url('${r.coverImage}')` }}
                  aria-hidden="true"
                />
                <div className={styles.coverOverlay} aria-hidden="true" />
                <div className={styles.coverTags}>
                  {r.tags.map((t, i) => (
                    <span
                      key={t}
                      className={cn(
                        styles.coverTag,
                        i === 0 && r.tags[1] && styles.coverTagPrimary
                      )}
                    >
                      {t}
                    </span>
                  ))}
                </div>
                <span className={styles.coverTimestamp}>{r.activity}</span>
              </div>

              <h3
                className={`${styles.cardTitle} font-headline-sm font-semibold`}
              >
                {r.title}
              </h3>

              <div className={`${styles.statsRow} font-code`}>
                <span className={styles.stat}>
                  <IconSpan
                    name="groups"
                    size={15}
                    className={styles.statIconPrimary}
                  />
                  {r.agents} 位智能体协同
                </span>
                <span aria-hidden="true">·</span>
                <span className={styles.stat}>
                  <IconSpan
                    name="menu_book"
                    size={15}
                    className={styles.statIconSecondary}
                  />
                  {r.citations} 篇引用
                </span>
              </div>
            </div>

            <div className={styles.footer}>
              <span className={`${styles.footerLabel} font-code`}>{r.footer}</span>
              <button
                type="button"
                className={cn(
                  styles.cta,
                  r.ctaPrimary ? styles.ctaPrimary : styles.ctaSecondary,
                  "font-body-sm font-medium"
                )}
              >
                <IconSpan
                  name={r.ctaPrimary ? "play_arrow" : "visibility"}
                  size={16}
                />
                <span>{r.ctaLabel}</span>
              </button>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}