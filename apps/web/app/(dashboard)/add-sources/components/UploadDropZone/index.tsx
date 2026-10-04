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

export function UploadDropZone({ onFilesSelected }: UploadDropZoneProps) {
  const [dragOver, setDragOver] = React.useState(false)
  const inputRef = React.useRef<HTMLInputElement>(null)

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
    const files = Array.from(e.dataTransfer.files ?? [])
    if (files.length > 0) onFilesSelected(files)
  }

  const onClick = () => {
    inputRef.current?.click()
  }

  const onPickerChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? [])
    if (files.length > 0) onFilesSelected(files)
    e.target.value = ''
  }

  return (
    <section className={styles.section}>
      <div className={styles.head}>
        <div className={styles.headLeft}>
          <span className={styles.headDot} />
          <span className={`${styles.headTitle} font-headline-sm`}>本地原始文件摄入</span>
        </div>
        <span className={`${styles.headMeta} font-code`}>MAX 100MB / FILE</span>
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
          支持 PDF, DOCX, Markdown, HTML, TXT, EPUB 以及音视频录音 (MP3/MP4 自动 Whisper 转录)
        </p>
        <div className={styles.chips}>
          {['PDF (Native/Scanned)', 'Whisper v3 MP3/MP4', 'MDX / Jupyter', 'XLSX / Parquet'].map(
            (label) => (
              <span key={label} className={`${styles.chip} font-code`}>
                {label}
              </span>
            ),
          )}
        </div>
        <div className={styles.legend}>
          <span className={styles.legendItem}>
            <IconSpan name="verified" size={14} className="text-primary-container" />
            <span>单文件上限 100MB</span>
          </span>
          <span className={styles.legendDot}>·</span>
          <span className={styles.legendItem}>
            <IconSpan name="dynamic_feed" size={14} className="text-primary-container" />
            <span>支持多文件并发上传</span>
          </span>
          <span className={styles.legendDot}>·</span>
          <span className={styles.legendItem}>
            <IconSpan name="document_scanner" size={14} className="text-primary-container" />
            <span>自动 OCR 与图表语义解析</span>
          </span>
        </div>
      </div>
    </section>
  )
}
