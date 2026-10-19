'use client'

import * as React from 'react'
import styles from './index.module.css'

/**
 * 底部条：条数摘要 + 体积合计。
 *
 * ## 为什么没有分页按钮
 *
 * 设计稿上有「1/2/3/…/122」那套翻页，但后端 `GET /api/v1/sources` **没有
 * 分页参数**——一次把该用户的全部资料返回（`gateway/sources.py` 的
 * `list_sources`，`total` 就是 `len(items)`）。摆一排点不动的页码按钮，
 * 等于宣称「这些资料只占第 1 页」，比不显示更糟。
 *
 * 真要分页得先给后端加 `limit/offset`，那是另一个批次。在那之前这里只
 * 如实显示「显示 N 条，共 M 条」。
 */
export function SourcePagination({ shown, total }: { shown: number; total: number }) {
  return (
    <div className={styles.bar}>
      <span className={`${styles.summary} font-body-sm`}>
        显示 <span className={`${styles.count} font-code`}>{shown}</span> 条 / 共{' '}
        <span className={`${styles.count} font-code`}>{total}</span> 条
      </span>
    </div>
  )
}
