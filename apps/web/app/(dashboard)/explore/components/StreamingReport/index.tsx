'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import type { Citation } from '../../constants'
import { parseBlocks, parseInline, type Block, type InlineToken } from '@/lib/markdown/parse'
import styles from './index.module.css'

export interface StreamingReportProps {
  onSelectCitation: (citation: Citation) => void
  /** 引用表，由后端 reference 事件下发。编号对不上正文的 `[n]` 时角标不可点。 */
  citations: Citation[]
  /** 累积的报告正文（delta 拼接而成）。空串表示还没收到第一个字。 */
  streamedText: string
  /** 流是否仍在进行。只有它在跑且已有正文时才画光标。 */
  streaming: boolean
  /** 本轮真实提问；空态引导用它。 */
  query?: string
}

/**
 * 把正文里的 `[n]` 切成可点的角标，其余原样输出。
 *
 * 后端在 prompt 里要求模型「句末标上对应编号，如 [1] 或 [1][2]」，但那是
 * 软约束——模型会编造越界编号、也会漏标。所以解析必须容错：命中引用表的
 * 渲染成角标，查不到的退回裸字符，让用户自己看出模型编了号。
 *
 * ## 顺序：先切行内格式，再在每个 token 内切角标
 *
 * 反过来（先按 `[n]` 切）会把跨角标的行内格式切断——`parseInline` 的
 * 正则不跨 token 边界，`**结论 ` 后面跟着角标按钮，` 成立**` 又在另一个
 * 段里，两边的 `**` 都配不上对，加粗完全失效；`` `data[1]` `` 里的
 * `[1]` 还会被误当成角标，而它其实只是数组下标。
 *
 * 所以顺序是：行内格式 → token 内再找角标 → 角标渲染成按钮。
 */
function renderInlineWithCitations(
  text: string,
  citations: Citation[],
  onSelect: (c: Citation) => void,
  keyPrefix: string,
): React.ReactNode[] {
  return parseInline(text).map((token, i) => (
    <InlineNode
      key={`${keyPrefix}-${i}`}
      token={token}
      citations={citations}
      onSelect={onSelect}
    />
  ))
}

const CITE_SPLIT_RE = /(\[\d+\])/

function InlineNode({
  token,
  citations,
  onSelect,
}: {
  token: InlineToken
  citations: Citation[]
  onSelect: (c: Citation) => void
}) {
  // 行内代码里的方括号是**内容**不是引用——`` `data[1]` `` 的 [1] 指的是
  // 数组下标，切成角标会让用户点到一个毫不相干的资料。整段不切。
  if (token.kind === 'code') {
    return <code className={styles.inlineCode}>{token.value}</code>
  }

  const parts = token.value.split(CITE_SPLIT_RE).map((part, i) => {
    const match = /^\[(\d+)\]$/.exec(part)
    if (!match?.[1]) return <React.Fragment key={i}>{part}</React.Fragment>
    return (
      <Cite
        key={i}
        id={Number(match[1])}
        citations={citations}
        onSelect={onSelect}
      />
    )
  })

  // 粗体里的角标仍然是引用——模型写「**结论 [1] 成立**」是常见写法，
  // 把角标渲染成按钮的同时保留加粗，两者不冲突。
  if (token.kind === 'bold') return <strong>{parts}</strong>
  return parts
}

function Cite({
  id,
  citations,
  onSelect,
}: {
  id: number
  citations: Citation[]
  onSelect: (citation: Citation) => void
}) {
  const citation = citations.find((c) => c.n === id)
  // 编号对不上引用表时退回裸字符。后端 citation.py 明确说 [n] 只是 prompt
  // 里的软约束，模型可能编造或漏标编号——不能崩，也不能吞掉这个号。
  if (!citation) return <span>[{id}]</span>

  return (
    <button
      type="button"
      className={styles.cite}
      onClick={() => onSelect(citation)}
      title={`${citation.title}${citation.page != null ? ` · 第 ${citation.page} 页` : ''}`}
    >
      {id}
    </button>
  )
}

/**
 * 流式报告主区 —— 提问徽章 + Markdown 正文（穿插 [n] 引文上标），
 * 流仍在进行且已有正文时末尾带闪烁光标。
 */
export function StreamingReport({
  onSelectCitation,
  citations,
  streamedText,
  streaming,
  query,
}: StreamingReportProps) {
  const blocks = React.useMemo(() => parseBlocks(streamedText), [streamedText])
  const showCursor = streaming && streamedText.length > 0

  return (
    <article className={styles.article}>
      <div className={styles.meta}>
        <span className={styles.metaLabel}>
          <IconSpan name="bolt" size={14} className={styles.metaIcon} />
          <span>研究课题:</span>
        </span>
        <span className={styles.metaQuery}>{query ? `“${query}”` : '尚未提问'}</span>
      </div>

      {streamedText === '' ? (
        <EmptyHint streaming={streaming} />
      ) : (
        <div className={styles.prose}>
          {blocks.map((block, i) => (
            <BlockView
              key={i}
              block={block}
              citations={citations}
              onSelect={onSelectCitation}
              // 光标挂最后一块，且只在真的还在流时显示。
              cursor={showCursor && i === blocks.length - 1}
            />
          ))}
        </div>
      )}
    </article>
  )
}

function BlockView({
  block,
  citations,
  onSelect,
  cursor,
}: {
  block: Block
  citations: Citation[]
  onSelect: (c: Citation) => void
  cursor: boolean
}) {
  const inline = (text: string, key: string) =>
    renderInlineWithCitations(text, citations, onSelect, key)

  switch (block.kind) {
    case 'heading': {
      const Tag = block.level === 2 ? 'h2' : block.level === 3 ? 'h3' : 'h4'
      return (
        <Tag className={styles.heading} data-level={block.level}>
          {inline(block.text, `h${block.level}`)}
          {cursor && <span className={styles.cursor} />}
        </Tag>
      )
    }
    case 'ul':
      return (
        <ul className={styles.list}>
          {block.items.map((item, i) => (
            <li key={i}>
              {inline(item, `ul${i}`)}
              {cursor && i === block.items.length - 1 && <span className={styles.cursor} />}
            </li>
          ))}
        </ul>
      )
    case 'ol':
      return (
        <ol className={styles.list}>
          {block.items.map((item, i) => (
            <li key={i}>
              {inline(item, `ol${i}`)}
              {cursor && i === block.items.length - 1 && <span className={styles.cursor} />}
            </li>
          ))}
        </ol>
      )
    case 'paragraph':
      return (
        <p className={styles.paragraph}>
          {inline(block.text, 'p')}
          {cursor && <span className={styles.cursor} />}
        </p>
      )
    case 'table':
      return (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                {block.header.map((h, i) => (
                  <th key={i}>{inline(h, `th${i}`)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, r) => (
                <tr key={r}>
                  {row.map((cell, c) => (
                    <td key={c}>
                      {inline(cell, `td${r}-${c}`)}
                      {cursor && r === block.rows.length - 1 && c === row.length - 1 && (
                        <span className={styles.cursor} />
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )
  }
}

function EmptyHint({ streaming }: { streaming: boolean }) {
  return (
    <div className={styles.empty}>
      <IconSpan name="search" size={22} className={styles.emptyIcon} />
      <p className={styles.emptyText}>
        {streaming ? '正在检索资料…' : '在下方输入研究问题，或键入 / 选用提问模板。'}
      </p>
      <p className={styles.emptySub}>
        检索范围限于你已上传的私有资料与公开来源，报告中的每条结论都会标注引用来源。
      </p>
    </div>
  )
}
