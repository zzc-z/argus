"use client";

import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import { cn } from "@/lib/utils";
import { type BenchmarkCard } from "../../mock";
import styles from "./index.module.css";

export interface BenchmarkBarsProps {
  cards: BenchmarkCard[];
  /** Optional header legend (shown above the grid). */
  showLegend?: boolean;
}

/**
 * SECTION 03 benchmark visualization — two horizontal-bar pairs
 * (Llama 3 70B / Mixtral 8x22B). Pure presentation.
 */
export function BenchmarkBars({ cards, showLegend = true }: BenchmarkBarsProps) {
  return (
    <div className={styles.wrap}>
      {showLegend && (
        <div className={cn(styles.legend, "font-code")}>
          <span className={styles.legendItem}>
            <span className={cn(styles.legendSwatch, styles.swatchMuted)} />
            H100 (FP8)
          </span>
          <span className={styles.legendItem}>
            <span className={cn(styles.legendSwatch, styles.swatchPrimary)} />
            B200 (FP4 Native)
          </span>
        </div>
      )}

      <div className={styles.grid}>
        {cards.map((c) => (
          <div key={c.id} className={styles.card}>
            <div className={styles.cardTop}>
              <div className={styles.cardTitleRow}>
                <span className={cn(styles.cardTitle, "font-headline-sm")}>
                  {c.title}
                </span>
                <span className={cn(styles.cardSubtitle, "font-code")}>
                  {c.subtitle}
                </span>
              </div>
              <p className={cn(styles.cardHint, "font-label-sm")}>
                单位：Tokens/秒/卡 (越高越优)
              </p>
            </div>

            <div className={styles.bars}>
              {c.bars.map((b, idx) => (
                <div key={idx} className={styles.barRow}>
                  <div className={cn(styles.barLabels, "font-label-sm")}>
                    <span className={b.emphasize ? styles.barLabelPrimary : ""}>
                      {b.label}
                    </span>
                    <span
                      className={cn(
                        "font-code",
                        b.emphasize ? styles.barValuePrimary : ""
                      )}
                    >
                      {b.valueLabel}
                    </span>
                  </div>
                  <div className={styles.barTrack}>
                    <div
                      className={cn(
                        styles.barFill,
                        b.tone === "muted" ? styles.barMuted : styles.barPrimary
                      )}
                      style={{ width: `${b.pct}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>

            <div className={cn(styles.cardFoot, "font-label-sm")}>
              <span>{c.envLine}</span>
              <span className={cn(styles.tailStat, "font-code")}>{c.tailStat}</span>
            </div>
          </div>
        ))}
      </div>

      <div className={cn(styles.epilogue, "font-body-md")}>
        <p>
          得益于 192GB 的单卡超大显存池，B200 允许在单张 GPU 上直接装载 70B 模型完整的 FP4 权重与高达 64k 的 KV 缓存，彻底免去了模型跨 GPU 张量并行（TP）带来的通信气泡惩罚。对于具有 176B 总参数、仅激活 39B 参数的 Mixtral 8x22B 而言，B200 的 NVLink Gen 5 使得 Expert 并行拓扑通信延时从 4.8ms 压缩至 0.65ms。
        </p>
      </div>

      <span className={styles.footnoteMarker} aria-hidden="true">
        <IconSpan name="north_east" size={14} className="text-on-surface-variant" />
      </span>
    </div>
  );
}
