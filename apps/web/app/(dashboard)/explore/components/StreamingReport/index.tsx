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
   * 引用表。缺省用 mock 的 CITATIONS；流式模式下由父组件用后端 reference
   * 事件覆盖。角标能否点开取决于它与正文里的 `[n]` 是否对得上。
   */
  citations?: Citation[]
  /**
   * 尾段已经「流式输入」的文本。
   * 当值为 `undefined` 时回退到静态 mock 文案（保持不传此 prop 也能跑）。
   */
  streamedText?: string
  /** 真实提问。缺省时用静态 mock 文案，保持组件可独立预览。 */
  query?: string
  /** 报告标题。缺省时用静态 mock 文案。 */
  title?: string
}

/**
 * 把正文里的 `[n]` 切成可点的角标，其余原样输出。
 *
 * 后端在 prompt 里要求模型「句末标上对应编号，如 [1] 或 [1][2]」，但那是
 * 软约束——模型会编造越界编号、也会漏标。所以解析必须容错：命中引用表的
 * 渲染成角标，查不到的退回裸字符，让用户自己看出模型编了号。
 *
 * 注意 textarea / p 里不能塞裸 `<button>` 之外的东西被读屏器误读，所以
 * 分隔符（含被吃掉的 `[n]` 本身）在命中与未命中时都要能还原出文本。
 */
function renderWithCitations(text: string, citations: Citation[], onSelect: (c: Citation) => void) {
  return text.split(/(\[\d+\])/).map((chunk, i) => {
    const match = /^\[(\d+)\]$/.exec(chunk)
    if (!match?.[1]) return chunk
    return <Cite key={`${i}-${chunk}`} id={Number(match[1])} citations={citations} onSelect={onSelect} />
  })
}

/**
 * 流式报告主区 —— H1、3 段正文（穿插 [n] 引文上标）、文中 3 列硬件指标卡、
 * 当前正在流式追加的段落末尾带闪烁光标。
 */
export function StreamingReport({
  onSelectCitation,
  citations = CITATIONS,
  streamedText,
  query,
  title,
}: StreamingReportProps) {
  const isStreaming = streamedText !== undefined
  // 光标：只在「已收到正文但流还没结束」时显示。之前拿长度和
  // TRAILING_BODY_FALLBACK 比——真实正文一旦超过 mock 的字数，
  // 光标就永久消失。
  const showCursor = isStreaming && streamedText.length > 0
  // 空串（还没收到第一个 delta）时不显示任何正文——页面不该先给出
    // 整份 mock 报告，也不该提前打「正在…」的预告。
  const trailingBody = isStreaming ? streamedText : TRAILING_BODY_FALLBACK

  return (
    <article className={styles.article}>
      {/* Query badge + model stamp */}
      <div className={styles.meta}>
        <span className={styles.metaLabel}>
          <IconSpan name="bolt" size={14} className={styles.metaIcon} />
          <span>研究课题:</span>
        </span>
        <span className={styles.metaQuery}>&quot;{query ?? REPORT_QUERY}&quot;</span>
      </div>

      {/* H1 */}
      <h1 className={styles.h1}>{title ?? REPORT_TITLE}</h1>

      {/* Prose */}
      <div className={styles.prose}>
        {!isStreaming && (
          <>
        <p className={styles.p1}>
          从 NVIDIA Hopper 架构 (H100 SXM) 迁移至最新部署的 Blackwell 计算平台 (B200 / GB200
          NVL72），标志着高并发大语言模型 (LLM) 推理经济性迎来结构性拐点
          <Cite id={1} citations={citations} onSelect={onSelectCitation} />
          。尽管 H100 已经确立了 FP8 张量计算作为主流前沿模型（如 Llama 3 70B 和 Mixtral
          8x22B）的标准部署格式，但 Blackwell 进一步引入了集成微张量缩放的第二代 Transformer
          引擎，并提供原生 FP4 精度支持
          <Cite id={2} citations={citations} onSelect={onSelectCitation} />， 在同等功耗预算下实现了每瓦特 Token
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
          </>
        )}
        {!isStreaming && (
          <>
        <p>
          在显存子系统方面，带宽规格从 H100 的 3.35 TB/s 扩充至 Blackwell 的 8.0 TB/s
          HBM3e。在生成式自回归解码阶段——即显存总线带宽长期占据绝对瓶颈 的关键环节——Blackwell
          允许单机架域直接装载 1.8 万亿参数级别的 MoE 权重检查点，彻底消除了跨节点传统 InfiniBand
          串行化通信损耗
          <Cite id={3} citations={citations} onSelect={onSelectCitation} />
          。根据来自一线超大规模数据中心的基准 验证，在 70B 级别模型的高饱和批处理场景（Batch Size =
          128）下，单 Token 吐字延迟由 H100 的 42ms 骤降至约 14ms
          <Cite id={2} citations={citations} onSelect={onSelectCitation} />。
        </p>
          </>
        )}

        <p className={styles.p3}>
          {isStreaming
            ? renderWithCitations(trailingBody, citations, onSelectCitation)
            : trailingBody}
          {!isStreaming && (
            <Cite id={1} citations={citations} onSelect={onSelectCitation} />
          )}
          {showCursor && <span className={styles.cursor} />}
        </p>
      </div>
    </article>
  )
}

interface CiteProps {
  id: number
  citations: Citation[]
  onSelect: (citation: Citation) => void
}

/** Citation superscript [n] button. */
function Cite({ id, citations, onSelect }: CiteProps) {
  const citation = citations.find((c) => c.n === id)
  // 编号对不上引用表时退回裸字符。后端 citation.py 明确说 [n] 只是 prompt
  // 里的软约束，模型可能编造或漏标编号——不能崩，也不能吞掉这个号。
  if (!citation) return <span>[{id}]</span>

  return (
    <button
      type="button"
      className={styles.cite}
      onClick={() => onSelect(citation)}
      title={`${citation.title}${citation.page != null ? ` · 第 ${citation.page} 段` : ''}`}
    >
      {id}
    </button>
  )
}
