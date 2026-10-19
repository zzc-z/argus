'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import styles from './index.module.css'

/**
 * 拖拽上传区。drag-over 状态由一个 useState 控制。
 * 拖放或点击 → 通过 `onFilesSelected` 回调把选中的 File 数组抛出。
 */
export interface UploadDropZoneProps {
  /** Called when the user drops files onto the zone or activates the picker. */
  onFilesSelected: (files: File[]) => void
}

/** 后端 `_EXT_TO_TYPE` 认的扩展名。前端同款校验，让不支持的文件在
 *  上传前就被拦下，而不是等一个 415 白跑一趟。 */
const ACCEPTED = ['.pdf', '.docx', '.html', '.htm', '.txt', '.md', '.markdown']

function rejectedNames(files: File[]): string[] {
  return files
    .filter((f) => !ACCEPTED.some((ext) => f.name.toLowerCase().endsWith(ext)))
    .map((f) => f.name)
}

export function UploadDropZone({ onFilesSelected }: UploadDropZoneProps) {
  const [dragOver, setDragOver] = React.useState(false)
  const [rejected, setRejected] = React.useState<string[]>([])
  const inputRef = React.useRef<HTMLInputElement>(null)

  // 不支持的文件就地丢掉并列出文件名，其余照常上传——为一个 .xlsx
  // 拒绝整个拖放批次，比让用户自己再拖一次更糟。
  const forward = (files: File[]) => {
    if (files.length === 0) return
    const bad = rejectedNames(files)
    setRejected(bad)
    // 部分成功：能传的照常传，被拒的列出来。整批拒绝会让用户
    // 为一个 .xlsx 把所有文件重拖一遍。
    const ok = files.filter((f) => !bad.includes(f.name))
    if (ok.length > 0) onFilesSelected(ok)
  }

  const onDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragOver(true)
  }

  const onDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragOver(false)
  }

  const onDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragOver(false)
    forward(Array.from(e.dataTransfer.files ?? []))
  }

  const onClick = () => {
    inputRef.current?.click()
  }

  const onPickerChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    forward(Array.from(e.target.files ?? []))
    e.target.value = ''
  }

  return (
    <section className={styles.section}>
      <div className={styles.head}>
        <div className={styles.headLeft}>
          <span className={styles.headDot} />
          <span className={`${styles.headTitle} font-headline-sm`}>本地原始文件摄入</span>
        </div>
        <span className={`${styles.headMeta} font-code`}>MAX 50MB / FILE</span>
      </div>

      <div
        className={`${styles.dropZone} ${dragOver ? styles.dropZoneActive : ''}`}
        onDragOver={onDragOver}
        onDragEnter={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        onClick={onClick}
        role="button"
        tabIndex={0}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          hidden
          onChange={onPickerChange}
          data-testid="upload-input"
        />
        <div className={styles.dropIcon}>
          <IconSpan name="cloud_upload" size={24} className="text-primary-container" />
        </div>
        <p className={`${styles.dropTitle} font-body-md font-medium`}>
          拖拽文件至此处,或 <span className={styles.dropLink}>点击浏览本地文件</span>
        </p>
        <p className={`${styles.dropSub} font-body-sm`}>
          支持 PDF、Word（DOCX）、Markdown、纯文本（TXT）、HTML
        </p>
        <div className={styles.chips}>
          {/* 与后端 `_EXT_TO_TYPE` 逐一对齐。设计稿上的 EPUB / MP3-MP4 /
              MDX / XLSX 后端一律 415——留着这些 chip 等于承诺一个做不到的
              功能。 */}
          {['PDF', 'DOCX', 'Markdown', 'TXT', 'HTML'].map((label) => (
            <span key={label} className={`${styles.chip} font-code`}>
              {label}
            </span>
          ))}
        </div>
        {/* 「一次可传多个文件」不是「并发」：page.tsx 的 handleFiles 是
            `for...of await` 顺序传的。后端 upload_source 一次只接一个
            文件，并发只是把 N 个请求同时打出去，没有收益。
            「扫描件暂不支持」对应后端 PdfParser——PDF 提不出文字时直接
            抛 ParseError，后端没有 OCR。 */}
        <div className={styles.legend}>
          <span className={styles.legendItem}>
            <IconSpan name="verified" size={14} className="text-primary-container" />
            <span>单文件上限 50MB</span>
          </span>
          <span className={styles.legendDot}>·</span>
          <span className={styles.legendItem}>
            <IconSpan name="dynamic_feed" size={14} className="text-primary-container" />
            <span>一次可传多个文件</span>
          </span>
          <span className={styles.legendDot}>·</span>
          <span className={styles.legendItem}>
            <IconSpan name="document_scanner" size={14} className="text-primary-container" />
            <span>文本型 PDF，扫描件暂不支持</span>
          </span>
        </div>
        {rejected.length > 0 && (
          <p className={styles.dropError} role="alert">
            不支持的文件类型：{rejected.join('、')}。仅支持 PDF / DOCX / Markdown / TXT /
            HTML。（.doc 是 Word 旧版二进制格式，请另存为 .docx 或导出 PDF）
          </p>
        )}
      </div>
    </section>
  )
}
