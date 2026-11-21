'use client'

import * as React from 'react'
import {
  Actions,
  Avatar,
  DotBadge,
  IconLabel,
  type ActionBtn,
} from '@/components/common/TableCells'
import {
  PlainTable,
  type PlainTableColumnDef,
  type PlainTableSelection,
} from '@/components/common/PlainTable'

import styles from './index.module.css'
import { type SourceRow } from '../../lib/sourceTypes'

/* ── 列定义 ──────────────────────────────────────────────────
 * 表格骨架（裸 table / thead 浅底 / row hover / divide-y）由 PlainTable 接管。
 * 业务 cell 全部用 TableCells 原语；本文件 CSS 只剩列宽/对齐微调。
 *
 * 列定义是**工厂**而不是常量：操作列的「设为生效版」按钮需要回调，
 * 而回调来自页面层。模块级常量拿不到它——把它做成工厂，
 * 由 SourceTable 在渲染时按当前回调生成。 */

/** 构造列定义。`onActivate` 不传时归档版本没有「设为生效版」按钮。 */
function buildColumns(
  onActivate?: (id: number) => void,
): ReadonlyArray<PlainTableColumnDef<SourceRow>> {
  return [
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
        {/* URL 建源的 size_bytes 是 null（抓到内容前没有 Content-Length）。
            占位「—」和下面实打实的「3 切片」摆在一起会读成「没有大小
            却有切片」，所以这一格没体积时直接不渲染主行。 */}
        {row.size && <span className={`${styles.sizePrimary} font-code`}>{row.size}</span>}
        <span className={`${styles.sizeMeta} font-code`}>{row.chunks}</span>
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
    id: 'version',
    cell: (row) => <VersionCell row={row} />,
    header: '版本',
  },
  {
    id: 'time',
    cell: (row) => <span className={`${styles.time} font-code`}>{row.timeLabel}</span>,
    header: '时间',
  },
  {
    id: 'actions',
    cell: (row) => <SourceRowActions row={row} onActivate={onActivate} />,
    header: '操作',
    align: 'right',
    width: '132px',
  },
  ]
}

/* ── 行操作按钮组 ──────────────────────────────────────────── */

type SourceActionsByTone = Partial<Record<SourceRow['status'], ReadonlyArray<ActionBtn>>>

function SourceRowActions({ row, onActivate }: { row: SourceRow; onActivate?: (id: number) => void }) {
  const byTone = React.useMemo<SourceActionsByTone>(
    () => ({
      live: [{ label: '暂停' }],
      processing: [
        { label: '取消', tone: 'danger' },
        { label: '详情', tone: 'plain' },
      ],
      ready: [{ label: '查看切片' }, { icon: 'more_vert', ariaLabel: '更多操作' }],
      failed: [{ label: '查看切片' }, { icon: 'more_vert', ariaLabel: '更多操作' }],
    }),
    [],
  )
  // 归档版本多一个「设为生效版」按钮。
  //
  // 只在归档版本上出现：生效版本已经是生效的，给它一个同义的按钮是噪音。
  // 点了它，同组其他版本转归档，这份转生效——于是它进检索池。
  //
  // **只在已索引的版本上出现**（``row.status === 'ready'``）：没建成索引
  // 的版本接管生效位，等于「整组都搜不到」——它一条切片都没有，而它顶掉
  // 的旧版是唯一能用的那份。后端也会以 409 拒掉这种请求，
  // 前端不给点不出错的按钮。
  const canActivate = row.archived && row.status === 'ready' && Boolean(onActivate)
  const withActivate = React.useMemo<SourceActionsByTone>(
    () =>
      canActivate
        ? {
            ...byTone,
            ready: [...(byTone.ready ?? []), { label: '设为生效版', tone: 'plain' }],
          }
        : byTone,
    [canActivate, byTone],
  )

  // 「设为生效版」要带 onClick，其余按钮没有回调（渲染成 disabled）。
  // Actions 原语按 label 建 key，所以这里要给按钮一个稳定的 label。
  const withHandlers = React.useMemo<SourceActionsByTone>(() => {
    if (!canActivate) return withActivate
    const attach = (list: ReadonlyArray<ActionBtn> | undefined): ActionBtn[] =>
      (list ?? []).map((btn) =>
        btn.label === '设为生效版'
          ? { ...btn, onClick: () => onActivate?.(row.id) }
          : btn,
      )
    return {
      ...withActivate,
      ready: attach(withActivate.ready),
    }
  }, [canActivate, row.id, onActivate, withActivate])

  return <Actions tone={row.status} byTone={withHandlers} />
}

/* ── 状态徽章 ──────────────────────────────────────────────── */

function StatusBadgeCell({ row }: { row: SourceRow }) {
  if (row.status === 'ready') {
    return <DotBadge tone="ready" label="已完全索引" className="font-label-sm" />
  }
  if (row.status === 'processing') {
    return (
      <DotBadge tone="processing" label="增量切片中" animate="spin" className="font-label-sm" />
    )
  }
  return <DotBadge tone="failed" label="索引告警" className="font-label-sm" />
}

/**
 * 版本列。
 *
 * 三种形态：
 * - 归档版本（`archived`）→ 「旧版」徽章（idle 色），**带版本号**
 * - 有版本号的生效版本 → 「第 N 版」徽章，ready 色
 * - 不参与分组 → 「—」
 *
 * **归档态必须标出来**：归档版本留档但不参与本地检索，用户看到它
 * 「搜不到」会以为坏了。标成「旧版」说明的是「它被更新的版本取代了」，
 * 而「索引告警」说的是「它坏了」——两件事要能分辨。
 *
 * **归档徽章必须带版本号**：一库里有多组资料时，全是「旧版」的徽章
 * 长得一模一样——用户点第 3 行的「设为生效版」，以为在切某份合同，
 * 实际切的是另一份资料的旧版。所以用后端给的 ``version_no`` 补上。
 */
function VersionCell({ row }: { row: SourceRow }) {
  if (row.archived) {
    return (
      <DotBadge
        tone="idle"
        label={row.versionNo > 1 ? `旧版 · 第 ${row.versionNo} 版` : '旧版'}
        className="font-label-sm"
      />
    )
  }
  if (!row.versionLabel) {
    return <span className="font-label-sm">—</span>
  }
  return <DotBadge tone="ready" label={row.versionLabel} className="font-label-sm" />
}

export interface SourceTableProps {
  data: ReadonlyArray<SourceRow>
  selection: PlainTableSelection<SourceRow>
  columns?: ReadonlyArray<PlainTableColumnDef<SourceRow>>
  /**
   * 点「设为生效版」时回调，传资料 id。
   *
   * 不传 = 归档版本没有那个按钮——列定义要靠它才知道要不要渲染。
   */
  onActivate?: (id: number) => void
  className?: string
}

/**
 * Sources 表格 —— PlainTable 的业务薄包装。
 *  - 列定义默认由 buildColumns 按当前回调生成
 *  - 表格骨架 / checkbox 列 / selection 受控由 PlainTable 提供
 *  - 业务 cell 全部由 TableCells 原语组装（IconLabel / DotBadge / ProgressBar / Actions / Avatar）
 */
export function SourceTable({
  data,
  selection,
  columns,
  onActivate,
  className,
}: SourceTableProps) {
  // 列定义按 onActivate 生成，所以每次渲染都是新数组。
  // 它只传给 PlainTable（不是 hook 依赖），不会造成重渲染循环。
  const resolvedColumns = columns ?? buildColumns(onActivate)
  return (
    <PlainTable<SourceRow>
      columns={resolvedColumns}
      data={data}
      getRowId={(r) => String(r.id)}
      selection={selection}
      className={className}
    />
  )
}
