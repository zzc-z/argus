"use client";

import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import { queueItems, queueSummary, type QueueItem } from "../../mock";
import styles from "./index.module.css";

/**
 * Ingestion queue monitor — 4 task items + ETA footer + action row.
 * Per-item rendering branches on `done` / `waveform` flags.
 */
export function QueueMonitor() {
  return (
    <section className={styles.panel}>
      <div className={styles.head}>
        <div className={styles.headLeft}>
          <span className={`${styles.headTitle} font-headline-sm`}>当前处理队列</span>
          <span className={`${styles.headChip} font-code`}>{queueSummary.total} Tasks</span>
          <span className={`${styles.headSub} font-label-sm`}>
            并发处理配额: {queueSummary.capacity}
          </span>
        </div>
        <button type="button" className={`${styles.clearBtn} font-label-sm`}>
          <IconSpan name="clear_all" size={15} />
          <span>清空已完成</span>
        </button>
      </div>

      <div className={styles.list}>
        {queueItems.map((item) => (
          <QueueRow key={item.id} item={item} />
        ))}
      </div>

      <div className={styles.footer}>
        <div className={styles.summary}>
          <div className={styles.summaryLeft}>
            <IconSpan name="speed" size={16} className="text-primary-container" />
            <span className="font-code">
              预计剩余处理:{" "}
              <strong className={`${styles.summaryStrong} font-code`}>
                {queueSummary.etaSeconds}
              </strong>
            </span>
          </div>
          <span className="font-code">
            GPU 负载:{" "}
            <strong className={`${styles.summaryGpu} font-code`}>{queueSummary.gpuLoad}</strong>
          </span>
        </div>
        <div className={styles.actions}>
          <button type="button" className={`${styles.cancelBtn} font-body-sm`}>
            取消队列
          </button>
          <button type="button" className={`${styles.confirmBtn} font-body-sm font-medium`}>
            <IconSpan name="verified" size={18} />
            <span>确认全部入库</span>
          </button>
        </div>
      </div>
    </section>
  );
}

function QueueRow({ item }: { item: QueueItem }) {
  const accentClass = styles[`accent_${item.iconAccent}`];

  return (
    <div className={styles.item}>
      <div className={styles.itemHead}>
        <div className={styles.itemLeft}>
          <div className={`${styles.itemIcon} ${accentClass}`}>
            <IconSpan name={item.iconName} size={16} />
          </div>
          <div className={styles.itemText}>
            <span className={`${styles.itemName} font-body-sm font-medium`}>{item.name}</span>
            <div className={`${styles.itemMeta} font-code`}>
              <span>{item.kindLabel}</span>
              <span>·</span>
              <span>{item.size}</span>
              <span>·</span>
              <span
                className={`${item.done ? styles.itemMetaDone : styles.itemMetaLive} font-code`}
              >
                {item.progressLabel}
              </span>
            </div>
          </div>
        </div>

        {item.done ? (
          <span className={`${styles.doneBadge} font-label-sm`}>
            <IconSpan name="check_circle" size={13} />
            已索引
          </span>
        ) : (
          <span className={`${styles.itemPercent} font-code`}>{item.progress}%</span>
        )}
      </div>

      {/* Audio waveform visual (item.tsmc-audio) */}
      {item.waveform && (
        <div className={styles.waveRow}>
          <div className={styles.wave}>
            {[
              { h: "full", op: 80, pulse: true },
              { h: 8, op: 60 },
              { h: "full", op: 90, pulse: true },
              { h: 6, op: 40 },
              { h: "full", op: 100 },
              { h: 10, op: 70, pulse: true },
              { h: 4 },
              { h: 6 },
              { h: 4 },
              { h: 8 },
            ].map((bar, i) => {
              const height =
                bar.h === "full" ? "100%" : typeof bar.h === "number" ? `${bar.h}px` : "auto";
              const opacity = bar.op ?? 50;
              return (
                <span
                  key={i}
                  className={`${styles.waveBar} ${bar.pulse ? "animate-pulse" : ""}`}
                  style={{
                    height: height === "auto" ? undefined : height,
                    backgroundColor:
                      opacity >= 50
                        ? `color-mix(in srgb, var(--token-primary-container, #7039f9) ${opacity}%, transparent)`
                        : "var(--token-surface-container-high, #e7e8e9)",
                  }}
                />
              );
            })}
          </div>
          {item.timeCurrent && item.timeTotal && (
            <span className={`${styles.waveTime} font-code`}>
              {item.timeCurrent} / {item.timeTotal}
            </span>
          )}
        </div>
      )}

      <div className={styles.bar}>
        <div
          className={`${item.done ? styles.barFillDone : styles.barFillLive}`}
          style={{ width: `${item.progress}%` }}
        />
      </div>

      <div className={styles.statusRow}>
        <span
          className={`${styles.statusText} font-label-sm ${
            item.entities ? styles.statusTextDone : ""
          }`}
        >
          {item.entities ? (
            <>
              <IconSpan name="hub" size={14} className="text-emerald-600" />
              <span className="font-medium">{item.entities}</span>
            </>
          ) : (
            <span>{item.statusLabel}</span>
          )}
        </span>

        <div className={styles.statusRight}>
          {item.timing && !item.done && (
            <span className={`${styles.statusTiming} font-code`}>{item.timing}</span>
          )}
          {item.done && (
            <span className={`${styles.statusTiming} font-code`}>{item.timing}</span>
          )}
          {!item.done && !item.waveform && (
            <button
              type="button"
              className={styles.cancelIconBtn}
              aria-label="取消任务"
              title="取消任务"
            >
              <IconSpan name="close" size={15} />
            </button>
          )}
          {!item.done && item.waveform && (
            <button
              type="button"
              className={styles.cancelIconBtn}
              aria-label="取消任务"
              title="取消任务"
            >
              <IconSpan name="close" size={15} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}