"use client";

import * as React from "react";
import Link from "next/link";
import { IconSpan } from "@/components/common/IconSpan";
import styles from "./index.module.css";

/**
 * Page header — breadcrumbs (back to /sources) + title + live status chip.
 */
export function AddSourcesHeader() {
  return (
    <header className={styles.header}>
      <div className={styles.crumbs}>
        <Link href="/sources" className={`${styles.crumbLink} font-label-sm`}>
          <IconSpan name="database" size={15} />
          <span>资料库</span>
        </Link>
        <span className={`${styles.crumbSep}`}>/</span>
        <span className={`${styles.crumbCurrent} font-label-sm font-medium`}>添加新数据源</span>
        <span className={`${styles.crumbChip} font-code`}>INGEST_V2</span>
      </div>

      <div className={styles.titleRow}>
        <div className={styles.titleLeft}>
          <h1 className={`${styles.title} font-headline-lg font-semibold tracking-tight`}>
            添加研究资料{" "}
            <span className={`${styles.titleAccent} font-code font-normal`}>Add Sources</span>
          </h1>
          <p className={`${styles.subtitle} font-body-sm`}>
            上传离线研究文档、输入网页链接或订阅专业 RSS 数据流以扩充 Argus
            知识库与推演图谱
          </p>
        </div>

        <div className={styles.titleRight}>
          <span className={`${styles.statusChip} font-code`}>
            <span className={`${styles.statusDot} animate-pulse`} />
            EMBED_WORKER_ONLINE
          </span>
          <div className={`${styles.statusSep} hidden sm:block`} />
          <span className={`${styles.statusNote} font-label-sm hidden sm:inline`}>
            端到端加密通道 · 零留存模式
          </span>
        </div>
      </div>
    </header>
  );
}