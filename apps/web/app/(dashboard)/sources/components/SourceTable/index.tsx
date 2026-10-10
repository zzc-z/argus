'use client'

import * as React from 'react'
import {
  Actions,
  Avatar,
  DotBadge,
  IconLabel,
  ProgressBar,
  type ActionBtn,
} from '@/components/common/TableCells'
import {
  PlainTable,
  type PlainTableColumnDef,
  type PlainTableSelection,
} from '@/components/common/PlainTable'
import { type SourceRow } from '../../mock'
import styles from './index.module.css'

/* ── 列定义 ──────────────────────────────────────────────────
 * 表格骨架（裸 table / thead 浅底 / row hover / divide-y）由 PlainTable 接管。
 * 业务 cell 全部用 TableCells 原语；本文件 CSS 只剩列宽/对齐微调。 */

export const sourceColumns: ReadonlyArray<PlainTableColumnDef<SourceRow>> = [
  {
    id: 'title',
    cell: (row) => (
      <Avatar
        icon={row.iconName}
        iconTone={
          row.iconAccent === 'primary'
            ? 'processing'
            : row.iconAccent === 'purple'
              ? 'live'
              : row.iconAccent === 'red'
                ? 'failed'
                : row.iconAccent === 'amber'
                  ? 'idle'
                  : 'idle'
        }
        title={row.title}
        subtitle={row.meta}
        href="#"
        titleClassName="font-headline-sm"
        subtitleClassName="font-code"
      />
    ),
    header: '资料名称与来源描述',
    width: '280px',
    cellClassName: styles.titleCell,
  },
  {
    id: 'kind',
    cell: (row) => <span className={`${styles.kindBadge} font-code`}>{row.kind}</span>,
    header: '类型',
  },
  {
    id: 'size',
    cell: (row) => (
      <div className={styles.sizeBlock}>
        <span
          className={`${styles.sizePrimary} font-code ${row.status === 'live' ? styles.sizePrimaryLive : ''}`}
        >
          {row.size}
        </span>
        <span className={`${styles.sizeMeta} font-code`}>{row.chunks}</span>
        {row.status === 'processing' && row.progress !== undefined && (
          <ProgressBar label={`Embedding ${row.progress}%`} percent={row.progress} />
        )}
      </div>
    ),
    header: '切片状态 / 规模',
    cellClassName: styles.sizeCell,
  },
  {
    id: 'citations',
    cell: (row) => (
      <IconLabel
        icon="auto_stories"
        iconClassName="text-secondary"
        iconSize={15}
        label={`${row.citations} 篇引用`}
        className="font-body-sm"
      />
    ),
    header: '关联报告',
  },
  {
    id: 'status',
    cell: (row) => <StatusBadgeCell row={row} />,
    header: '索引状态',
    cellClassName: styles.statusCell,
  },
  {
    id: 'time',
    cell: (row) => <span className={`${styles.time} font-code`}>{row.timeLabel}</span>,
    header: '时间',
  },
  {
    id: 'actions',
    cell: (row) => <SourceRowActions row={row} />,
    header: '操作',
    align: 'right',
    width: '132px',
  },
]

/* ── 行操作按钮组 ──────────────────────────────────────────── */

type SourceActionsByTone = Partial<Record<SourceRow['status'], ReadonlyArray<ActionBtn>>>

function SourceRowActions({ row }: { row: SourceRow }) {
  const byTone = React.useMemo<SourceActionsByTone>(
    () => ({
      live: [{ label: '暂停' }],
      processing: [
        { label: '取消', tone: 'danger' },
        { label: '详情', tone: 'plain' },
      ],
      ready: [
        { label: '查看切片' },
        { icon: 'more_vert', ariaLabel: '更多操作' },
      ],
      failed: [
        { label: '查看切片' },
        { icon: 'more_vert', ariaLabel: '更多操作' },
      ],
    }),
    [],
  )
  return <Actions tone={row.status} byTone={byTone} />
}

/* ── 状态徽章 ──────────────────────────────────────────────── */

function StatusBadgeCell({ row }: { row: SourceRow }) {
  if (row.status === 'ready') {
    return <DotBadge tone="ready" label="已就绪" className="font-label-sm" />
  }
  if (row.status === 'processing') {
    return <DotBadge tone="processing" label="处理中" animate="spin" className="font-label-sm" />
  }
  if (row.status === 'live') {
    return <DotBadge tone="live" label="持续监听" animate="ping" className="font-label-sm" />
  }
  return <DotBadge tone="failed" label="失败" className="font-label-sm" />
}

export interface SourceTableProps {
  data: ReadonlyArray<SourceRow>
  selection: PlainTableSelection<SourceRow>
  columns?: ReadonlyArray<PlainTableColumnDef<SourceRow>>
  className?: string
}

/**
 * Sources 表格 —— PlainTable 的业务薄包装。
 *  - 列定义默认从 sourceColumns 注入
 *  - 表格骨架 / checkbox 列 / selection 受控由 PlainTable 提供
 *  - 业务 cell 全部由 TableCells 原语组装（IconLabel / DotBadge / ProgressBar / Actions / Avatar）
 */
export function SourceTable({
  data,
  selection,
  columns = sourceColumns,
  className,
}: SourceTableProps) {
  return (
    <PlainTable<SourceRow>
      columns={columns}
      data={data}
      getRowId={(r) => r.id}
      selection={selection}
      className={className}
    />
  )
}