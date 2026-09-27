import type { ColumnDef, RowData, TableFeatures } from '@tanstack/react-table'

/** DataTable 通用契约。
 *  - columns 由调用方传入，cell / header 由调用方组装（业务样式由调用方 CSS 提供）
 *  - 列宽 / 对齐通过 meta 注入 CSS 变量（flex 布局，不需要 subgrid）
 *  - selection 受控：调用方持有 selectedIds，回调只通知切换
 */

export type DataTableAlign = 'left' | 'right' | 'center'

export interface ColumnWidth {
  /** 固定最小宽度（CSS 字符串，如 "17rem" / "120px"） */
  minWidth?: string
  /** flex 生长系数；>0 表示弹性列。缺省按内容收缩 */
  flex?: number
  /** 固定 basis 宽度（CSS 字符串，如 "120px"）；flex=0 时用于固定列宽 */
  basis?: string
  /** 最大宽度（CSS 字符串，如 "430px"）；超过则不再膨胀 */
  maxWidth?: string
}

export interface DataTableColumnMeta {
  /** row cell 对齐方式 */
  align?: DataTableAlign
  /** header cell 对齐方式（缺省 = 与 align 一致） */
  headerAlign?: DataTableAlign
  /** 列宽契约 */
  width?: ColumnWidth
  /** 行 / header cell 附加 className（业务背景色、padding 微调等） */
  cellClassName?: string
}

/** v9 ColumnDef 第二个泛型 TData 必须 extends RowData；这里放宽到任意 object
 *  让调用方不必为每个新数据模型手动 extends RowData。 */
export type DataTableColumnDef<TData extends object = object> = ColumnDef<
  TableFeatures,
  TData & RowData
> & {
  meta?: DataTableColumnMeta
}

export interface DataTableSelection<TData> {
  selectedIds: ReadonlySet<string>
  onToggle: (id: string) => void
  onToggleAll: () => void
  allSelected: boolean
  partiallySelected: boolean
  /** 自定义 row → selected 推断（默认从 selectedIds.has(id) 推断） */
  isSelected?: (row: TData) => boolean
}

export interface DataTableProps<TData extends object = object> {
  columns: ReadonlyArray<DataTableColumnDef<TData>>
  data: ReadonlyArray<TData>
  getRowId?: (row: TData, index: number) => string
  /** 受控 selection；不传则表格没有内置复选框列，由调用方自行消费 selectedIds */
  selection?: DataTableSelection<TData>
  /** 行附加 className（如 running / banded / 异常状态） */
  rowClassName?: (row: TData, index: number) => string | undefined
  className?: string
}
