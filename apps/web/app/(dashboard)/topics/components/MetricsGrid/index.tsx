import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import { METRICS } from "../../mock";
import styles from "./index.module.css";

/**
 * Four-card metrics row beneath the header. Each card renders one icon + label,
 * one large headline value, and a contextual footer (delta %, progress bar, etc).
 */
export function MetricsGrid() {
  return (
    <section className={styles.grid}>
      {METRICS.map((m) => (
        <article key={m.id} className={styles.card}>
          <div className={styles.cardHead}>
            <span className={`${styles.label} font-label-sm uppercase tracking-wider`}>
              {m.label}
            </span>
            <IconSpan
              name={m.icon}
              size={18}
              className={
                m.iconTone === "primary"
                  ? "text-primary"
                  : m.iconTone === "error"
                    ? "text-error"
                    : "text-secondary"
              }
            />
          </div>
          <div className={styles.cardValue}>
            <span className={`${styles.value} font-headline-lg font-semibold text-on-surface`}>
              {m.value}
            </span>
            <span className={`${styles.caption} font-label-sm text-secondary`}>{m.caption}</span>
          </div>
          {m.accent?.kind === "progress" && m.accent.ratio !== undefined && (
            <div className={styles.progress} role="presentation">
              <span
                className={styles.progressFill}
                style={{ width: `${Math.max(0, Math.min(1, m.accent.ratio)) * 100}%` }}
              />
            </div>
          )}
          {m.accent?.kind === "footer" && (
            <div className={`${styles.accentFooter} ${m.iconTone === "error" ? styles.accentPrimary : ""} font-label-sm text-secondary`}>
              {m.iconTone === "error" && <span className={styles.accentDot} />}
              {m.accent.text}
            </div>
          )}
          {m.accent?.kind === "delta" && (
            <span className={`${styles.delta} font-code text-primary`}>{m.accent.text}</span>
          )}
        </article>
      ))}
    </section>
  );
}
