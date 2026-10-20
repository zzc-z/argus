'use client'

import * as React from 'react'
import { parseBlocks, parseInline, type Block, type InlineToken } from '@/lib/markdown/parse'
import type { ReportCitationV } from '@/lib/api/reports'
import { CitationMark } from '../CitationMark'
import styles from './index.module.css'

export interface ChapterSectionProps {
  /** 报告正文 markdown 原文。 */
  content: string
  /** 引用表，用于判断正文里的 `[n]` 能不能解析到条目。 */
  citations: ReportCitationV[]
  /** 点击正文角标时回调角标编号。 */
  onCitationClick?: (n: number) => void
}

/**
 * 正文区：把后端返回的 markdown 渲染成结构化内容，角标可点。
 *
 * ## 为什么角标要自己切
 *
 * 后端 prompt 里「句末标上对应编号」只是软约束——模型会编造越界编号，
 * 也会漏标。所以正文里的 `[n]` 未必在引用表里：能查到就渲染成可点的
 * 角标，查不到就退回裸字符，让用户自己看出模型编了号。
 */
export function ChapterSection({ content, citations, onCitationClick }: ChapterSectionProps) {
  const blocks = React.useMemo(() => parseBlocks(content), [content])
  const resolvable = React.useMemo(() => new Set(citations.map((c) => c.n)), [citations])

  return (
    <article className={styles.card}>
      <div className={styles.prose}>
        {blocks.map((block, i) => (
          <BlockView
            key={i}
            block={block}
            resolvable={resolvable}
            onCitationClick={onCitationClick}
          />
        ))}
      </div>
    </article>
  )
}

interface BlockViewProps {
  block: Block
  resolvable: Set<number>
  onCitationClick?: (n: number) => void
}

function BlockView({ block, resolvable, onCitationClick }: BlockViewProps) {
  switch (block.kind) {
    case 'heading': {
      const Tag = block.level === 2 ? 'h2' : block.level === 3 ? 'h3' : 'h4'
      return (
        <Tag className={styles.heading} data-level={block.level}>
          <Inline text={block.text} resolvable={resolvable} onCitationClick={onCitationClick} />
        </Tag>
      )
    }
    case 'paragraph':
      return (
        <p className={styles.paragraph}>
          <Inline text={block.text} resolvable={resolvable} onCitationClick={onCitationClick} />
        </p>
      )
    case 'ul':
      return (
        <ul className={styles.list}>
          {block.items.map((item, i) => (
            <li key={i}>
              <Inline text={item} resolvable={resolvable} onCitationClick={onCitationClick} />
            </li>
          ))}
        </ul>
      )
    case 'ol':
      return (
        <ol className={styles.list}>
          {block.items.map((item, i) => (
            <li key={i}>
              <Inline text={item} resolvable={resolvable} onCitationClick={onCitationClick} />
            </li>
          ))}
        </ol>
      )
    case 'table':
      return (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                {block.header.map((h, i) => (
                  <th key={i}>
                    <Inline text={h} resolvable={resolvable} onCitationClick={onCitationClick} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, r) => (
                <tr key={r}>
                  {row.map((cell, c) => (
                    <td key={c}>
                      <Inline
                        text={cell}
                        resolvable={resolvable}
                        onCitationClick={onCitationClick}
                      />
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

interface InlineProps {
  text: string
  resolvable: Set<number>
  onCitationClick?: (n: number) => void
}

/**
 * 行内渲染。
 *
 * ## 顺序：先切行内格式，再在每个 token 内切角标
 *
 * 反过来（先按 `[n]` 切）会把跨角标的行内格式切断——`parseInline` 的
 * 正则不跨 token 边界，`**结论 ` 后面跟着角标，` 成立**` 又在另一个
 * token 里，两边的 `**` 都配不上对，加粗完全失效；`` `data[1]` `` 里的
 * `[1]` 还会被误当成角标，而它其实只是数组下标。
 */
function Inline({ text, resolvable, onCitationClick }: InlineProps) {
  return (
    <>
      {parseInline(text).map((token, i) => (
        <InlineTokenView
          key={i}
          token={token}
          resolvable={resolvable}
          onCitationClick={onCitationClick}
        />
      ))}
    </>
  )
}

interface InlineTokenViewProps {
  token: InlineToken
  resolvable: Set<number>
  onCitationClick?: (n: number) => void
}

function InlineTokenView({ token, resolvable, onCitationClick }: InlineTokenViewProps) {
  // 行内代码里的方括号是**内容**不是引用——`` `data[1]` `` 的 [1] 指的是
  // 数组下标，切成角标会让用户点到一个毫不相干的资料。整段不切。
  if (token.kind === 'code') {
    return <code className={styles.inlineCode}>{token.value}</code>
  }

  const parts = splitCitations(token.value).map((part, i) => {
    const n = citationNumber(part)
    if (n == null) return <React.Fragment key={i}>{part}</React.Fragment>
    return (
      <CitationMark
        key={i}
        n={n}
        resolvable={resolvable.has(n)}
        onClick={() => onCitationClick?.(n)}
      />
    )
  })

  // 粗体里的角标仍然是引用——模型写「**结论 [1] 成立**」是常见写法，
  // 把角标渲染成按钮的同时保留加粗，两者不冲突。
  if (token.kind === 'bold') return <strong>{parts}</strong>
  return <>{parts}</>
}

/** 切出 `[n]` 段落，保留分隔用的捕获组。 */
function splitCitations(text: string): string[] {
  return text.split(/(\[\d+\])/).filter((part) => part !== '')
}

/** `part` 是 `[n]` 时返回 n，否则 null。 */
function citationNumber(part: string): number | null {
  const match = /^\[(\d+)\]$/.exec(part)
  return match?.[1] ? Number(match[1]) : null
}
