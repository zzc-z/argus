'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import styles from './index.module.css'

/**
 * Left filter sidebar — type / indexing status / timeline / tags / storage quota.
 * State is purely visual (counts/checked/active) — matches the static design.
 */
export function SourceFilterSidebar() {
  return (
    <aside className={styles.sidebar}>
      {/* Section: File Types */}
      <section className={styles.section}>
        <div className={styles.sectionHead}>
          <span className={`${styles.sectionTitle} font-label-sm uppercase tracking-wider`}>
            类型筛选 Type
          </span>
          <span className={`${styles.sectionMeta} font-code`}>5 类</span>
        </div>
        <div className={styles.checkList}>
          {[
            { label: 'PDF 文档', count: 310, checked: true },
            { label: '网页 URL', count: 287, checked: true },
            { label: 'RSS 实时流', count: 148, checked: false },
            { label: '技术论文 Arxiv', count: 102, checked: false },
            { label: '音视频转录', count: 32, checked: false },
          ].map((row) => (
            <label key={row.label} className={styles.checkRow}>
              <div className={styles.checkText}>
                <input
                  type="checkbox"
                  defaultChecked={row.checked}
                  className={`${styles.checkbox} accent-primary-container`}
                />
                <span className={`${styles.checkLabel} font-body-sm`}>{row.label}</span>
              </div>
              <span className={`${styles.checkCount} font-code`}>{row.count}</span>
            </label>
          ))}
        </div>
      </section>

      <div className={styles.divider} />

      {/* Section: Indexing Status */}
      <section className={styles.section}>
        <span className={`${styles.sectionTitle} font-label-sm uppercase tracking-wider`}>
          索引状态 Status
        </span>
        <div className={styles.checkList}>
          <label className={styles.checkRow}>
            <div className={styles.checkText}>
              <input
                type="checkbox"
                defaultChecked
                className={`${styles.checkbox} accent-primary-container`}
              />
              <span className={`${styles.checkLabel} font-body-sm`}>
                <span className={styles.dotEmerald} /> 已完全索引 Indexed
              </span>
            </div>
            <span className={`${styles.checkCount} font-code`}>812</span>
          </label>
          <label className={styles.checkRow}>
            <div className={styles.checkText}>
              <input
                type="checkbox"
                defaultChecked
                className={`${styles.checkbox} accent-primary-container`}
              />
              <span className={`${styles.checkLabel} font-body-sm`}>
                <span className={`${styles.dotPrimary} animate-pulse`} /> 增量切片中 Processing
              </span>
            </div>
            <span className={`${styles.checkCountActive} font-code`}>24</span>
          </label>
          <label className={styles.checkRow}>
            <div className={styles.checkText}>
              <input type="checkbox" className={`${styles.checkbox} accent-primary-container`} />
              <span className={`${styles.checkLabel} font-body-sm`}>
                <span className={styles.dotError} /> 索引告警 Failed
              </span>
            </div>
            <span className={`${styles.checkCountErr} font-code`}>11</span>
          </label>
        </div>
      </section>

      <div className={styles.divider} />

      {/* Section: Timeline */}
      <section className={styles.section}>
        <span className={`${styles.sectionTitle} font-label-sm uppercase tracking-wider`}>
          添加时间跨度 Timeline
        </span>
        <div className={styles.timelineGrid}>
          <button type="button" className={`${styles.timeBtn} font-body-sm`}>
            近 24 小时
          </button>
          <button
            type="button"
            className={`${styles.timeBtn} ${styles.timeBtnActive} font-body-sm font-medium`}
          >
            本周
          </button>
          <button type="button" className={`${styles.timeBtn} font-body-sm`}>
            本月
          </button>
          <button type="button" className={`${styles.timeBtn} font-body-sm`}>
            2026年
          </button>
        </div>
      </section>

      <div className={styles.divider} />

      {/* Section: Tags */}
      <section className={styles.section}>
        <div className={styles.sectionHead}>
          <span className={`${styles.sectionTitle} font-label-sm uppercase tracking-wider`}>
            课题与标签 Tags
          </span>
          <IconSpan
            name="filter_list"
            size={16}
            className="text-secondary hover:text-on-surface cursor-pointer"
          />
        </div>
        <div className={styles.tags}>
          {[
            { label: '#AI硬件架构', count: 142, active: false },
            { label: '#大模型推理', count: 98, active: true },
            { label: '#合规审计', count: 64, active: false },
            { label: '#财报数据', count: 53, active: false },
            { label: '#具身智能', count: 37, active: false },
          ].map((t) => (
            <button
              key={t.label}
              type="button"
              className={`${styles.tag} ${t.active ? styles.tagActive : ''} font-body-sm`}
            >
              <span className="text-[12px]">{t.label}</span>
              <span
                className={`${styles.tagCount} font-code text-[11px] ${t.active ? styles.tagCountActive : ''}`}
              >
                {t.count}
              </span>
            </button>
          ))}
        </div>
      </section>

      <div className={styles.divider} />

      {/* Storage quota */}
      <section className={styles.quota}>
        <div className={styles.quotaHead}>
          <div className={styles.quotaLabel}>
            <IconSpan name="pie_chart" size={16} />
            <span className={`${styles.quotaText} font-label-sm`}>向量库配额</span>
          </div>
          <span className={`${styles.quotaPercent} font-code`}>24.8% 已用</span>
        </div>
        <div className={styles.quotaBar}>
          <div className={styles.quotaFill} style={{ width: '24.8%' }} />
        </div>
        <div className={`${styles.quotaFooter} font-code`}>
          <span>12.4 GB 已用</span>
          <span>50.0 GB 总量</span>
        </div>
      </section>
    </aside>
  )
}
