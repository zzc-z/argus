'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import styles from './index.module.css'
import type { QueueRowItem } from '../../lib/queueTypes'

export interface QueueMonitorProps {
  items: QueueRowItem[]
}

/**
 * 摄取队列。
 *
 * ## 显示什么、不显示什么
 *
 * 设计稿上这里有音频波形、「已注入概念图谱 N 个知识实体」、`3.2s` 耗时、
 * 取消按钮——**后端都没有**：没有音频转录、没有知识图谱、ingest 不返回
 * 耗时、没有取消端点。画上去就全是编的，所以删掉，只留真有的：阶段名、
 * 切片数、失败原因。
 *
 * 进度条同理：后端只有 6 个阶段没有百分比，所以进行中画成**不定长动画**
 * 而不是假的 37%。
 */
export function QueueMonitor({ items }: QueueMonitorProps) {
  return (
    <section className={styles.panel} aria-label="摄取队列">
      <header className={styles.head}>
        <span className={`${styles.headTitle} font-label-sm uppercase tracking-wider`}>
          摄取队列
        </span>
        <span className={`${styles.headCount} font-code`}>{items.length}</span>
      </header>

      {items.length === 0 ? (
        <p className={styles.empty}>队列为空。拖入文件或粘贴网页地址后，进度会显示在这里。</p>
      ) : (
        <ul className={styles.list} role="list">
          {items.map((item) => (
            <QueueRow key={item.id} item={item} />
          ))}
        </ul>
      )}
    </section>
  )
}

function QueueRow({ item }: { item: QueueRowItem }) {
  return (
    <li className={styles.item}>
      <div className={styles.itemHead}>
        <div className={styles.itemLeft}>
          <div className={styles.itemIcon}>
            <IconSpan name={item.iconName} size={16} />
          </div>
          <div className={styles.itemText}>
            <span className={`${styles.itemName} font-body-sm font-medium`}>{item.name}</span>
            <div className={`${styles.itemMeta} font-code`}>
              <span>{item.kindLabel}</span>
              {/* 体积是可选的：URL 建源在抓到内容之前 size_bytes 就是
                  null，渲染出来会变成「文稿 · · 已索引」这种孤儿分隔符。
                  过滤掉再 join，而不是给 null 找个假值。 */}
              {item.size ? (
                <>
                  <span>·</span>
                  <span>{item.size}</span>
                </>
              ) : null}
              <span>·</span>
              <span
                className={`${item.done ? styles.itemMetaDone : styles.itemMetaLive} font-code`}
              >
                {item.progressLabel}
              </span>
            </div>
          </div>
        </div>

        {item.failed ? (
          <span className={`${styles.failedBadge} font-label-sm`}>
            <IconSpan name="error" size={13} />
            失败
          </span>
        ) : item.done ? (
          <span className={`${styles.doneBadge} font-label-sm`}>
            <IconSpan name="check_circle" size={13} />
            已索引
          </span>
        ) : (
          <span className={`${styles.itemStage} font-label-sm`}>{item.stageLabel}</span>
        )}
      </div>

      {item.error && (
        <p className={styles.errorText} role="alert">
          {item.error}
        </p>
      )}

      <div
        className={styles.bar}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        // 进行中不给 valuenow——后端只有阶段没有百分比，给一个数就是编的。
        // aria-valuetext 说清楚「到哪一步了」，读屏用户拿到的是阶段名。
        {...(item.done || item.failed
          ? { 'aria-valuenow': item.failed ? 0 : 100 }
          : { 'aria-valuetext': item.progressLabel })}
      >
        <div
          className={
            item.failed ? styles.barFillFailed : item.done ? styles.barFillDone : styles.barFillLive
          }
          style={item.done || item.failed ? { width: '100%' } : undefined}
        />
      </div>
    </li>
  )
}
