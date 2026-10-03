'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import {
  DataTable,
  type DataTableColumnDef,
  type DataTableProps,
  type DataTableSelection,
} from '@/components/common/DataTable'
import { TABLE_HEADER, type Report } from '../../mock'
import styles from './index.module.css'

/* ── 列定义 ──────────────────────────────────────────────────
 * 提到模块级常量：业务无关部分（id / header / cell）抽出，便于多视图复用 / 测试 mock。
 * 列宽 / 对齐 / cellClassName 通过 meta 注入 DataTable，由 flex 布局接管。 */

export const reportColumns: ReadonlyArray<DataTableColumnDef<Report>> = [
  {
    id: 'title',
    header: () => (
      <button type="button" className={styles.headerBtn}>
        <span>{TABLE_HEADER.title}</span>
        <span className={styles.headerSortIcon} aria-hidden="true">
          ↓
        </span>
      </button>
    ),
    cell: ({ row }) => {
      const r = row.original as Report
      const isRunning = r.status === 'running'
      return (
        <div className={styles.titleWrap}>
          <div className={styles.titleLine}>
            {isRunning && <span className={styles.runningDot} aria-hidden="true" />}
            <a className={styles.title} href={`/report/${r.id}`}>
              {r.title}
            </a>
            <button
              type="button"
              className={`${styles.star} ${r.starred ? styles.starred : ''}`}
              aria-label={r.starred ? '取消星标' : '星标关注'}
              title={r.starred ? '取消星标' : '星标关注'}
            >
              <IconSpan name="star" size={16} />
            </button>
          </div>
          <p className={styles.summary}>{r.summary}</p>
        </div>
      )
    },
    meta: {
      align: 'left',
      width: { minWidth: '370px', flex: 2 },
      cellClassName: styles.colTitle,
    },
  },
  {
    id: 'topic',
    header: () => (
      <button type="button" className={styles.headerBtn}>
        <span>{TABLE_HEADER.topic}</span>
      </button>
    ),
    cell: ({ row }) => {
      const t = (row.original as Report).topic
      return (
        <span className={`${styles.topicBadge} ${styles[`topic-${t.tone}`] ?? ''}`}>{t.label}</span>
      )
    },
    meta: {
      align: 'left',
      width: { flex: 0, minWidth: '120px', basis: '120px' },
      cellClassName: styles.colTopic,
    },
  },
  {
    id: 'generatedAt',
    header: () => (
      <button type="button" className={styles.headerBtn}>
        <span>{TABLE_HEADER.generatedAt}</span>
      </button>
    ),
    cell: ({ row }) => {
      const r = row.original as Report
      const isRunning = r.status === 'running'
      return (
        <div className={styles.timeCol}>
          <span className={isRunning ? styles.timePrimary : styles.timeDefault}>
            {r.generatedAt}
          </span>
          <span className={styles.timeSub}>{r.generatedAtSub}</span>
        </div>
      )
    },
    meta: {
      align: 'left',
      headerAlign: 'left',
      width: { minWidth: '5.5rem', flex: 0.5 },
      cellClassName: styles.colGeneratedAt,
    },
  },
  {
    id: 'sources',
    header: () => (
      <button type="button" className={styles.headerBtn}>
        <span>{TABLE_HEADER.sources}</span>
      </button>
    ),
    cell: ({ row }) => {
      const r = row.original as Report
      const isRunning = r.status === 'running'
      return (
        <div className={styles.sourcesCol}>
          <div className={styles.sourcesLeft}>
            <span className={styles.sources}>{r.sourcesCount} 篇</span>
            <span className={styles.sourcesSub}>{r.viewsCount} 阅</span>
          </div>
          {isRunning ? (
            <span className={styles.runningBadge}>
              <IconSpan name="progress_activity" size={13} className={styles.runningBadgeIcon} />
              <span>正在合成 ({r.runningProgress ?? 0}%)</span>
            </span>
          ) : (
            <span className={styles.verifiedBadge}>
              <IconSpan name="check_circle" size={14} />
              <span>已交叉验证</span>
            </span>
          )}
        </div>
      )
    },
    meta: {
      align: 'left',
      headerAlign: 'left',
      width: { flex: 0.75, minWidth: '5rem' },
      cellClassName: styles.colSources,
    },
  },
  {
    id: 'status',
    header: () => <span>{TABLE_HEADER.status}</span>,
    cell: ({ row }) => {
      const r = row.original as Report
      const isRunning = r.status === 'running'
      return (
        <div className={styles.actionsCol}>
          <div className={styles.actionGroup}>
            <button
              type="button"
              className={styles.actionBtn}
              aria-label={isRunning ? '查看运行中 DAG 图谱' : '阅读研报'}
              title={isRunning ? '查看运行中 DAG 图谱' : '阅读研报'}
            >
              <IconSpan name={isRunning ? 'account_tree' : 'visibility'} size={18} />
            </button>
            <button
              type="button"
              className={styles.actionBtn}
              aria-label={isRunning ? '暂停生成' : '导出 PDF'}
              title={isRunning ? '暂停生成' : '导出 PDF'}
            >
              <IconSpan name={isRunning ? 'pause' : 'download'} size={18} />
            </button>
            <button
              type="button"
              className={styles.actionBtn}
              aria-label="更多选项"
              title="更多选项"
            >
              <IconSpan name="more_horiz" size={18} />
            </button>
          </div>
        </div>
      )
    },
    meta: {
      align: 'right',
      headerAlign: 'right',
      width: { minWidth: '8rem' },
      cellClassName: styles.colStatus,
    },
  },
]

/** ReportTable props —— 兼容旧版散开字段 + 新版 selection 对象。
 *  调用方可以选其一；优先识别 selection（DataTable 原生形态），回退到 5 个散开字段。 */
export interface ReportTableProps {
  reports: ReadonlyArray<Report>
  /** 新版：DataTable 原生 selection 对象 */
  selection?: DataTableSelection<Report>
  /** 旧版散开字段 —— 调用方仍在用，向后兼容 */
  selectedIds?: ReadonlySet<string>
  onToggle?: (id: string) => void
  onToggleAll?: () => void
  allSelected?: boolean
  partiallySelected?: boolean
  /** 默认使用上方 reportColumns；调用方可在测试 / 替代视图中覆盖 */
  columns?: ReadonlyArray<DataTableColumnDef<Report>>
  rowClassName?: DataTableProps<Report>['rowClassName']
  className?: string
}

/**
 * Reports 表格 —— DataTable 的业务薄包装。
 *  - 列定义默认从 reportColumns 注入
 *  - 业务 cell 样式（badge / 时间 / 标题 / 操作）由本目录 CSS 提供
 *  - 选状态由 DataTable 受控；兼容旧版散开 props
 */
export function ReportTable(props: ReportTableProps) {
  const {
    columns = reportColumns,
    reports,
    selection,
    selectedIds,
    onToggle,
    onToggleAll,
    allSelected,
    partiallySelected,
    rowClassName,
    className,
  } = props

  // 优先用新版 selection，回退到散开字段
  const selectionProp: DataTableSelection<Report> | undefined = React.useMemo(() => {
    if (selection) return selection
    if (
      selectedIds &&
      onToggle &&
      onToggleAll &&
      allSelected !== undefined &&
      partiallySelected !== undefined
    ) {
      return { selectedIds, onToggle, onToggleAll, allSelected, partiallySelected }
    }
    return undefined
  }, [selection, selectedIds, onToggle, onToggleAll, allSelected, partiallySelected])

  // running 行注入背景色
  const finalRowClassName = React.useCallback(
    (row: Report, i: number) => {
      const base = rowClassName?.(row, i) ?? ''
      const isRunning = row.status === 'running' ? styles.runningRow : ''
      return [base, isRunning].filter(Boolean).join(' ')
    },
    [rowClassName],
  )

  return (
    <DataTable<Report>
      columns={columns}
      data={reports}
      getRowId={(r: Report) => r.id}
      selection={selectionProp}
      rowClassName={finalRowClassName}
      className={className}
    />
  )
}
