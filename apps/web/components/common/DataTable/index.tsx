"use client";

import * as React from "react";
import {
  flexRender,
  stockFeatures,
  useTable,
  type RowData,
} from "@tanstack/react-table";
import { cn } from "@/lib/utils";
import type {
  DataTableColumnDef,
  DataTableProps,
} from "./types";
import styles from "./index.module.css";

/**
 * 通用 DataTable（TanStack v9 + flex 列布局）。
 *  - 列定义通过 props 传入；cell / header 完全由调用方组装
 *  - 列宽通过 meta.width 注入 CSS 变量（flex 生长 / 固定最小宽）
 *  - selection 受控：调用方持有 selectedIds
 *  - 业务 cell 样式（badge / 标题 / 操作按钮等）由调用方 CSS 提供
 */
export function DataTable<TData extends RowData = RowData>({
  columns,
  data,
  getRowId,
  selection,
  rowClassName,
  className,
}: DataTableProps<TData>) {
  const masterRef = React.useRef<HTMLInputElement>(null);
  const sel = selection;

  React.useEffect(() => {
    if (masterRef.current && sel) {
      masterRef.current.indeterminate = sel.partiallySelected && !sel.allSelected;
    }
  }, [sel?.partiallySelected, sel?.allSelected]);

  // selection 模式：把内置复选框列塞到最前面
  const finalColumns = React.useMemo(() => {
    if (!sel) return columns;
    const selectCol: DataTableColumnDef<TData> = {
      id: "__select",
      header: () => (
        <input
          ref={masterRef}
          type="checkbox"
          checked={sel.allSelected}
          onChange={sel.onToggleAll}
          aria-label="全选"
          className={styles.checkboxInput}
        />
      ),
      cell: ({ row }) => {
        const id = getRowId ? getRowId(row.original as TData, row.index) : String(row.index);
        const checked = sel.isSelected
          ? sel.isSelected(row.original as TData)
          : sel.selectedIds.has(id);
        return (
          <input
            type="checkbox"
            checked={checked}
            onChange={() => sel.onToggle(id)}
            aria-label="选择行"
            className={styles.checkboxInput}
          />
        );
      },
      meta: { width: { minWidth: "2.75rem" }, align: "left" },
    };
    return [selectCol, ...columns];
  }, [columns, sel, getRowId]);

  const table = useTable({
    features: stockFeatures,
    data: data as TData[],
    columns: finalColumns as DataTableColumnDef<TData>[],
    getRowId: getRowId
      ? (row, index) => getRowId(row as TData, index)
      : undefined,
  });

  const renderCell = (
    columnId: string,
    meta: DataTableColumnDef<TData>["meta"],
    renderContent: () => React.ReactNode,
    isHeader: boolean,
  ) => {
    const width = meta?.width ?? {};
    const flex = width.flex !== undefined ? String(width.flex) : "0";
    const minWidth = width.minWidth ?? "auto";
    const basis = width.basis;
    const maxWidth = width.maxWidth;
    const effectiveAlign = isHeader
      ? (meta?.headerAlign ?? meta?.align ?? "left")
      : (meta?.align ?? "left");
    const alignCls =
      effectiveAlign === "right" ? styles.alignRight
        : effectiveAlign === "center" ? styles.alignCenter
          : styles.alignLeft;
    const extra = meta?.cellClassName ?? "";
    const cellBase = isHeader ? styles.headerCell : styles.rowCell;
    const style: React.CSSProperties = {
      ["--col-flex" as string]: flex,
      ["--col-min-w" as string]: minWidth,
      ...(basis !== undefined ? { flexBasis: basis } : {}),
      ...(maxWidth !== undefined ? { maxWidth } : {}),
    };
    const isSelect = columnId === "__select";
    return (
      <div
        key={columnId}
        className={cn(
          cellBase,
          isHeader ? styles.headerMarker : styles.rowMarker,
          alignCls,
          extra,
          isSelect ? styles.checkboxCell : "",
        )}
        style={style}
      >
        {renderContent()}
      </div>
    );
  };

  return (
    <div className={cn(styles.root, className)}>
      <div className={styles.header}>
        {table.getHeaderGroups().map((hg) => (
          <React.Fragment key={hg.id}>
            {hg.headers.map((header) =>
              renderCell(
                String(header.column.id),
                header.column.columnDef.meta as DataTableColumnDef<TData>["meta"],
                () =>
                  header.isPlaceholder
                    ? null
                    : flexRender(header.column.columnDef.header, header.getContext()),
                true,
              ),
            )}
          </React.Fragment>
        ))}
      </div>

      <div className={styles.body}>
        {table.getRowModel().rows.length === 0 ? (
          <div className={styles.empty}>暂无数据</div>
        ) : (
          table.getRowModel().rows.map((row, i) => {
            const extra = rowClassName?.(row.original as TData, i) ?? "";
            return (
              <div
                key={row.id}
                className={cn(styles.row, i % 2 === 1 ? styles.banded : "", extra)}
              >
                {row.getAllCells().map((cell) =>
                  renderCell(
                    String(cell.column.id),
                    cell.column.columnDef.meta as DataTableColumnDef<TData>["meta"],
                    () => flexRender(cell.column.columnDef.cell, cell.getContext()),
                    false,
                  ),
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

export type { DataTableColumnDef, DataTableProps, DataTableSelection } from "./types";