'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import { REPORT_QUERY, REPORT_TITLE, HARDWARE_METRICS, CITATIONS, type Citation } from '../../mock'
import styles from './index.module.css'

/** Static fallback for the trailing paragraph when no streamed text is passed. */
const TRAILING_BODY_FALLBACK =
  '更为关键的是,总体拥有成本 (TCO) 为大规模智算中心运营方带来了革命性的结构优化。以支撑 100,000 QPS 推理负载的集群规模测算,Blackwell 较同等吞吐 吞吐量的 Hopper 集群将数据中心综合电力消耗锐减 75%。目前主要的落地摩擦点集中于机房 二次液冷系统改建,因为 GB200 机柜强制要求采用单机柜高达 120kW 换热 密度的芯片级直触液冷回路...'

export interface StreamingReportProps {
  onSelectCitation: (citation: Citation) => void
  /**
   * Text that has "streamed in" so far for the trailing paragraph.
   * When `undefined` or empty the trailing paragraph falls back to
   * the static mock body (back-compat with pages that don't drive it).
   */
  streamedText?: string
}

/**
 * Hero streaming report — H1, 3 prose paragraphs interleaved with [n]
 * citation superscripts, mid-article 3-column hardware metrics card, and
 * a blinking cursor in the active streaming paragraph.
 */
export function StreamingReport({ onSelectCitation, streamedText }: StreamingReportProps) {
  const isStreaming = streamedText !== undefined
  const showCursor =
    isStreaming && streamedText.length > 0 && streamedText.length < TRAILING_BODY_FALLBACK.length
  // While a stream is active (even before the first char arrives), still show
  // the static fallback so the page never renders an empty paragraph.
  const trailingBody = isStreaming && streamedText.length > 0 ? streamedText : TRAILING_BODY_FALLBACK

  return (
    <article className={styles.article}>
      {/* Query badge + model stamp */}
      <div className={styles.meta}>
        <span className={styles.metaLabel}>
          <IconSpan name="bolt" size={14} className={styles.metaIcon} />
          <span>研究课题:</span>
        </span>
        <span className={styles.metaQuery}>&quot;{REPORT_QUERY}&quot;</span>
      </div>

      {/* H1 */}
      <h1 className={styles.h1}>{REPORT_TITLE}</h1>

      {/* Prose */}
      <div className={styles.prose}>
        <p className={styles.p1}>
          从 NVIDIA Hopper 架构 (H100 SXM) 迁移至最新部署的 Blackwell 计算平台 (B200 / GB200
          NVL72)，标志着高并发大语言模型 (LLM) 推理经济性迎来结构性拐点
          <Cite id={1} onSelect={onSelectCitation} />
          。尽管 H100 已经确立了 FP8 张量计算作为主流前沿模型（如 Llama 3 70B 和 Mixtral
          8x22B）的标准部署格式，但 Blackwell 进一步引入了集成微张量缩放的第二代 Transformer
          引擎，并提供原生 FP4 精度支持
          <Cite id={2} onSelect={onSelectCitation} />， 在同等功耗预算下实现了每瓦特 Token
          吞吐量的成倍跃升。
        </p>

        {/* Hardware metrics grid card */}
        <div className={styles.metricsCard}>
          <div className={styles.metricsHead}>
            <span>硬件规格演进差异</span>
            <span className={styles.metricsHeadEmphasis}>FP4/FP8 张量核心性能</span>
          </div>
          <div className={styles.metricsGrid}>
            {HARDWARE_METRICS.map((m) => (
              <div key={m.label} className={styles.metricCol}>
                <span className={styles.metricLabel}>{m.label}</span>
                <span className={styles.metricHeadline}>{m.headline}</span>
                <span
                  className={`${styles.metricDetail} ${
                    m.highlight ? styles.metricDetailHighlight : ''
                  }`}
                >
                  {m.detail}
                </span>
              </div>
            ))}
          </div>
        </div>

        <p>
          在显存子系统方面，带宽规格从 H100 的 3.35 TB/s 扩充至 Blackwell 的 8.0 TB/s
          HBM3e。在生成式自回归解码阶段——即显存总线带宽长期占据绝对瓶颈 的关键环节——Blackwell
          允许单机架域直接装载 1.8 万亿参数级别的 MoE 权重检查点，彻底消除了跨节点传统 InfiniBand
          串行化通信损耗
          <Cite id={3} onSelect={onSelectCitation} />
          。根据来自一线超大规模数据中心的基准 验证，在 70B 级别模型的高饱和批处理场景（Batch Size =
          128）下，单 Token 吐字延迟由 H100 的 42ms 骤降至约 14ms
          <Cite id={2} onSelect={onSelectCitation} />。
        </p>

        <p className={styles.p3}>
          {trailingBody}
          <Cite id={1} onSelect={onSelectCitation} />
          {showCursor && <span className={styles.cursor} />}
        </p>
      </div>
    </article>
  )
}

interface CiteProps {
  id: number
  onSelect: (citation: Citation) => void
}

/** Citation superscript [n] button. */
function Cite({ id, onSelect }: CiteProps) {
  const citation = CITATIONS.find((c) => c.id === id)
  if (!citation) return <span>[{id}]</span>

  return (
    <button
      type="button"
      className={styles.cite}
      onClick={() => onSelect(citation)}
      title={citation.sourceTitle}
    >
      {id}
    </button>
  )
}
