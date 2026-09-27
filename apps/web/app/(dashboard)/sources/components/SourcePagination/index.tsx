'use client'

import * as React from 'react'
import styles from './index.module.css'

/**
 * Bottom pagination bar — summary text + page buttons.
 * Matches design: 1-7 / 847 + pages 1/2/3/.../122 + 上一页 / 下一页.
 */
export function SourcePagination() {
  return (
    <div className={styles.bar}>
      <span className={`${styles.summary} font-body-sm`}>
        显示 <span className={`${styles.count} font-code`}>1 - 7</span> 条,共
        <span className={`${styles.count} font-code`}>847</span>
        条向量资料
      </span>
      <div className={styles.pages}>
        <button type="button" className={`${styles.navBtn} font-body-sm`} disabled>
          上一页
        </button>
        <button type="button" className={`${styles.pageBtnActive} font-code`} aria-current="page">
          1
        </button>
        <button type="button" className={`${styles.pageBtn} font-code`}>
          2
        </button>
        <button type="button" className={`${styles.pageBtn} font-code`}>
          3
        </button>
        <span className={`${styles.ellipsis} font-code`}>...</span>
        <button type="button" className={`${styles.pageBtn} font-code`}>
          122
        </button>
        <button type="button" className={`${styles.navBtn} font-body-sm`}>
          下一页
        </button>
      </div>
    </div>
  )
}
