"use client";

import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import styles from "./index.module.css";

/**
 * Drag-and-drop upload surface (visual only). Drag-over state is a single
 * useState toggle — matches the source HTML's behavior (bg swap on dragover).
 */
export function UploadDropZone() {
  const [dragOver, setDragOver] = React.useState(false);

  const onDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(true);
  };

  const onDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
  };

  const onDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
  };

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
        className={`${styles.dropZone} ${dragOver ? styles.dropZoneActive : ""}`}
        onDragOver={onDragOver}
        onDragEnter={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        role="button"
        tabIndex={0}
      >
        <div className={styles.dropIcon}>
          <IconSpan name="cloud_upload" size={24} className="text-primary-container" />
        </div>
        <p className={`${styles.dropTitle} font-body-md font-medium`}>
          拖拽文件至此处,或{" "}
          <span className={styles.dropLink}>点击浏览本地文件</span>
        </p>
        <p className={`${styles.dropSub} font-body-sm`}>
          支持 PDF, DOCX, Markdown, HTML, TXT, EPUB 以及音视频录音
          (MP3/MP4 自动 Whisper 转录)
        </p>
        <div className={styles.chips}>
          {["PDF (Native/Scanned)", "Whisper v3 MP3/MP4", "MDX / Jupyter", "XLSX / Parquet"].map(
            (label) => (
              <span key={label} className={`${styles.chip} font-code`}>
                {label}
              </span>
            )
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
  );
}