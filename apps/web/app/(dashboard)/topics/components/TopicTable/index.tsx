"use client";

import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import { TopicRow } from "../TopicRow";
import { TOPICS } from "../../mock";
import styles from "./index.module.css";

/**
 * Main subscription table. Owns table-wide state:
 *   - Selected row IDs (for batch actions in the footer)
 *   - Per-row topic mutation (frequency, active toggle) — passed down via setter
 *
 * Each row receives its current topic snapshot so toggling frequency / active
 * here updates the count badges under "全部" tab and the row itself.
 */
export function TopicTable() {
  const [topics, setTopics] = React.useState(TOPICS);
  const [selected, setSelected] = React.useState<Set<string>>(new Set());

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };
  const toggleSelectAll = () => {
    setSelected((prev) =>
      prev.size === topics.length ? new Set() : new Set(topics.map((t) => t.id))
    );
  };

  const updateTopic = (id: string, patch: Partial<(typeof topics)[number]>) => {
    setTopics((prev) => prev.map((t) => (t.id === id ? { ...t, ...patch } : t)));
  };

  const allChecked = selected.size === topics.length && topics.length > 0;
  const indeterminate = selected.size > 0 && selected.size < topics.length;

  // Footer summary rebuilt from topics so the count actually moves when toggles flip.
  const activeCount = topics.filter((t) => t.active).length;

  return (
    <div className={styles.shell}>
      <div className={styles.scroll}>
        <table className={styles.table}>
          <thead>
            <tr className={styles.theadRow}>
              <th className={styles.thCheck}>
                <input
                  type="checkbox"
                  aria-label="全选"
                  className={styles.checkbox}
                  checked={allChecked}
                  ref={(el) => {
                    if (el) el.indeterminate = indeterminate;
                  }}
                  onChange={toggleSelectAll}
                />
              </th>
              <th className={styles.thTitle}>课题名称与描述</th>
              <th className={styles.thSources}>监控信源配置</th>
              <th className={styles.thUpdated}>最近更新时间</th>
              <th className={styles.thUnread}>新捕获情报</th>
              <th className={styles.thFreq}>巡检更新频率</th>
              <th className={styles.thStatus}>运行状态</th>
              <th className={styles.thActions}>操作</th>
            </tr>
          </thead>
          <tbody className={styles.tbody}>
            {topics.map((topic) => (
              <TopicRow
                key={topic.id}
                topic={topic}
                checked={selected.has(topic.id)}
                onCheck={() => toggleSelect(topic.id)}
                onFrequencyChange={(value) => updateTopic(topic.id, { frequency: value })}
                onActiveChange={(active) => updateTopic(topic.id, { active })}
              />
            ))}
          </tbody>
        </table>
      </div>

      <div className={styles.footer}>
        <div className={styles.footerLeft}>
          <span className={`${styles.footerText} font-code`}>
            显示 1 - {topics.length} 条，共 {activeCount || topics.length} 个订阅课题
          </span>
          <span className={styles.footerSep} aria-hidden="true" />
          <div className={styles.selection}>
            <IconSpan name="check_box" size={16} className="text-primary" />
            <span className={`${styles.selectionLabel} font-label-sm`}>
              已选中 {selected.size} 项
            </span>
            <div className={styles.batchActions}>
              <button
                type="button"
                disabled={selected.size === 0}
                className={`${styles.batchBtn} font-code`}
              >
                批量暂停
              </button>
              <button
                type="button"
                disabled={selected.size === 0}
                className={`${styles.batchBtn} font-code`}
              >
                调整频率
              </button>
              <button
                type="button"
                disabled={selected.size === 0}
                className={`${styles.batchBtn} font-code`}
              >
                批量导出
              </button>
            </div>
          </div>
        </div>
        <div className={styles.pager}>
          <button type="button" disabled className={styles.pageBtn} aria-label="上一页">
            <IconSpan name="chevron_left" size={18} />
          </button>
          <button type="button" className={`${styles.pageBtn} ${styles.pageBtnActive} font-code`}>
            1
          </button>
          <button type="button" className={`${styles.pageBtn} font-code`}>
            2
          </button>
          <button type="button" className={styles.pageBtn} aria-label="下一页">
            <IconSpan name="chevron_right" size={18} />
          </button>
        </div>
      </div>
    </div>
  );
}
