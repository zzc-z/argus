"use client";

import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import { sourceRows, type SourceRow } from "../../mock";
import styles from "./index.module.css";

export interface SourceTableProps {
  selectedIds: Set<string>;
  onToggleRow: (id: string) => void;
}

/**
 * Dense data table — 7 design-matching rows with kind icon, status badge,
 * citations column. Selection state lives in the page; this component is
 * presentational + emits toggle events.
 */
export function SourceTable({ selectedIds, onToggleRow }: SourceTableProps) {
  return (
    <div className={styles.tableWrap}>
      <div className={styles.scrollX}>
        <table className={styles.table}>
          <thead>
            <tr className={`${styles.theadRow} font-label-sm`}>
              <th className={`${styles.th} ${styles.thSelect}`}>
                <span className="sr-only">选择行</span>
              </th>
              <th className={styles.th}>资料名称与来源描述</th>
              <th className={styles.th}>类型</th>
              <th className={styles.th}>切片状态 / 规模</th>
              <th className={styles.th}>关联报告</th>
              <th className={styles.th}>索引状态</th>
              <th className={styles.th}>时间</th>
              <th className={`${styles.th} ${styles.thAction}`}>操作</th>
            </tr>
          </thead>
          <tbody className={styles.tbody}>
            {sourceRows.map((row) => (
              <SourceRowView
                key={row.id}
                row={row}
                checked={selectedIds.has(row.id)}
                onToggle={() => onToggleRow(row.id)}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SourceRowView({
  row,
  checked,
  onToggle,
}: {
  row: SourceRow;
  checked: boolean;
  onToggle: () => void;
}) {
  const isProcessing = row.status === "processing";
  const isLive = row.status === "live";

  return (
    <tr
      className={`${styles.row} ${isProcessing ? styles.rowHighlight : ""}`}
      data-status={row.status}
    >
      <td className={`${styles.td} ${styles.tdSelect}`}>
        <input
          type="checkbox"
          checked={checked}
          onChange={onToggle}
          className={`${styles.checkbox} accent-primary-container`}
        />
      </td>
      <td className={`${styles.td} ${styles.tdTitle}`}>
        <div className={styles.titleInner}>
          <div className={`${styles.iconTile} ${styles[row.iconAccent]}`}>
            <IconSpan name={row.iconName} size={18} />
          </div>
          <div className={styles.titleText}>
            <a
              href="#"
              className={`${styles.titleLink} font-headline-sm group-hover:underline`}
            >
              {row.title}
            </a>
            <span className={`${styles.meta} font-code`}>{row.meta}</span>
          </div>
        </div>
      </td>
      <td className={styles.td}>
        <span className={`${styles.kindBadge} font-code`}>{row.kind}</span>
      </td>
      <td className={`${styles.td} ${styles.tdNowrap}`}>
        <div className={styles.sizeBlock}>
          <span
            className={`${styles.sizePrimary} font-code ${
              isLive ? styles.sizePrimaryLive : ""
            }`}
          >
            {row.size}
          </span>
          <span className={`${styles.sizeMeta} font-code`}>{row.chunks}</span>
          {isProcessing && row.progress !== undefined && (
            <div className={styles.progressWrap}>
              <div className={styles.progressHead}>
                <span className={`${styles.progressLabel} font-label-sm`}>
                  Embedding {row.progress}%
                </span>
              </div>
              <div className={styles.progressBar}>
                <div
                  className={styles.progressFill}
                  style={{ width: `${row.progress}%` }}
                />
              </div>
            </div>
          )}
        </div>
      </td>
      <td className={`${styles.td} ${styles.tdNowrap}`}>
        <span className={`${styles.cite} font-body-sm`}>
          <IconSpan name="auto_stories" size={15} className="text-secondary" />
          <span>{row.citations} 篇引用</span>
        </span>
      </td>
      <td className={`${styles.td} ${styles.tdNowrap}`}>
        <StatusBadge row={row} />
      </td>
      <td className={`${styles.td} ${styles.tdNowrap}`}>
        <span className={`${styles.time} font-code`}>{row.timeLabel}</span>
      </td>
      <td className={`${styles.td} ${styles.tdAction}`}>
        <div className={styles.actions}>
          {isLive ? (
            <button type="button" className={`${styles.rowBtn} font-body-sm`}>
              暂停
            </button>
          ) : isProcessing ? (
            <>
              <button type="button" className={`${styles.rowBtn} ${styles.rowBtnDanger} font-body-sm`}>
                取消
              </button>
              <button type="button" className={`${styles.rowBtn} ${styles.rowBtnPlain} font-body-sm`}>
                详情
              </button>
            </>
          ) : (
            <>
              <button type="button" className={`${styles.rowBtn} font-body-sm`}>
                查看切片
              </button>
              <button
                type="button"
                className={`${styles.iconBtn}`}
                aria-label="更多操作"
              >
                <IconSpan name="more_vert" size={18} />
              </button>
            </>
          )}
        </div>
      </td>
    </tr>
  );
}

function StatusBadge({ row }: { row: SourceRow }) {
  if (row.status === "ready") {
    return (
      <span className={`${styles.badge} ${styles.badgeReady} font-label-sm`}>
        <span className={styles.dotReady} />
        已就绪
      </span>
    );
  }
  if (row.status === "processing") {
    return (
      <span className={`${styles.badge} ${styles.badgeProcessing} font-label-sm`}>
        <span className={`${styles.spinDot} animate-spin`} />
        处理中
      </span>
    );
  }
  if (row.status === "live") {
    return (
      <span className={`${styles.badge} ${styles.badgeLive} font-label-sm`}>
        <span className={`${styles.dotLive} animate-ping`} />
        持续监听
      </span>
    );
  }
  return (
    <span className={`${styles.badge} ${styles.badgeFailed} font-label-sm`}>
      <span className={styles.dotFailed} />
      失败
    </span>
  );
}