/** PlainTable 通用契约 —— 裸 table 形态（无外层圆角容器/无斑马纹/无固定行高）。
 *  - columns 由调用方传入；cell / header 由调用方组装
 *  - selection 受控：调用方持有 selectedIds，回调只通知切换
 *  - 与 DataTable 的差别：PlainTable 不引 TanStack；视觉走"design 1:1"裸 table 风格
 */

export type PlainTableAlign = 'left' | 'right' | 'center'

export interface PlainTableColumnDef<TData> {
  /** 唯一 id；同时作为 thead/th 与 tbody/td 的 key */
  id: string
  /** 表头内容；字符串直接渲染，函数返回值用于复杂表头（按钮等） */
  header: React.ReactNode | (() => React.ReactNode)
  /** 行 cell 渲染函数 */
  cell: (row: TData) => React.ReactNode
  /** 列宽（CSS 字符串透传，如 '320px' / '40px'）；可省略 */
  width?: string
  /** 列对齐：影响 row cell；不传则跟随表头 */
  align?: PlainTableAlign
  /** 表头单独对齐 */
  headerAlign?: PlainTableAlign
  /** 行 cell 额外 className（业务 cell 背景/微调） */
  cellClassName?: string
}

export interface PlainTableSelection<TData> {
  selectedIds: ReadonlySet<string>
  onToggle: (id: string) => void
  onToggleAll: () => void
  allSelected: boolean
  partiallySelected: boolean
  /** 自定义 row → selected 推断（默认从 selectedIds.has(getRowId(row)) 推断） */
  isSelected?: (row: TData) => boolean
}

export interface PlainTableProps<TData> {
  columns: ReadonlyArray<PlainTableColumnDef<TData>>
  data: ReadonlyArray<TData>
  getRowId: (row: TData, index: number) => string
  /** 受控 selection；不传则表格没有内置复选框列 */
  selection?: PlainTableSelection<TData>
  /** 追加到 <table> 上 */
  className?: string
}