'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import { processingOptions, defaultTopicOptions } from '../../mock'
import styles from './index.module.css'

/**
 * Pipeline processing options — 4 checkbox cards + topic classifier dropdown.
 * All 4 boxes default to checked (matches design intent).
 */
export function ProcessingOptions() {
  return (
    <section className={styles.section}>
      <div className={styles.head}>
        <div className={styles.headLeft}>
          <IconSpan name="tune" size={20} className="text-primary-container" />
          <span className={`${styles.headTitle} font-headline-sm`}>
            智能解析与处理选项 (Processing DAG)
          </span>
        </div>
        <span className={`${styles.headChip} font-label-sm`}>Agent Pipeline v3</span>
      </div>

      <div className={styles.grid}>
        {processingOptions.map((opt) => (
          <label key={opt.title} className={styles.option}>
            <input type="checkbox" defaultChecked className="peer sr-only" />
            <span className={styles.optionBox}>
              <IconSpan name="check" size={14} className="text-on-primary" />
            </span>
            <div className={styles.optionText}>
              <span className={`${styles.optionTitle} font-body-sm font-medium`}>{opt.title}</span>
              <span className={`${styles.optionMeta} font-label-sm`}>{opt.meta}</span>
            </div>
          </label>
        ))}
      </div>

      <div className={styles.topicRow}>
        <div className={styles.topicLabel}>
          <IconSpan name="folder_special" size={18} className="text-secondary" />
          <span className={`${styles.topicText} font-body-sm font-medium`}>默认归入研究专题:</span>
        </div>
        <div className={styles.topicSelectWrap}>
          <select
            className={`${styles.topicSelect} font-body-sm`}
            defaultValue={defaultTopicOptions[0]?.value}
          >
            {defaultTopicOptions.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
      </div>
    </section>
  )
}
