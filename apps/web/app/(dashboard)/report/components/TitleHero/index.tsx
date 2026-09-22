"use client";

import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import { StatusDot } from "@/components/common/StatusDot";
import { cn } from "@/lib/utils";
import { reportMeta } from "../../mock";
import styles from "./index.module.css";

/**
 * Title hero — tag chips + h1 + meta info row.
 * Pure presentation; parent provides nothing.
 */
export function TitleHero() {
  const m = reportMeta;

  return (
    <section className={styles.card}>
      <div className={styles.tagRow}>
        {m.tags.map((tag) => (
          <span key={tag} className={cn(styles.tag, "font-label-sm")}>
            {tag}
          </span>
        ))}
        <span className={cn(styles.dagChip, "font-code")}>
          <StatusDot color="purple" ping />
          DAG 拓扑流水线已校验 (SHA-256: {m.dagSha})
        </span>
      </div>

      <h1 className={cn(styles.title, "font-headline-xl")}>{m.title}</h1>

      <div className={cn(styles.metaRow, "font-label-sm")}>
        <MetaItem icon="schedule" label={`${m.generatedHoursAgo} 小时前自动生成`} />
        <Sep />
        <MetaItem icon="smart_toy" label={`${m.agentCount} 个智能体协同构建`} />
        <Sep />
        <MetaItem icon="menu_book" label={`${m.citationCount} 篇权威白皮书引用`} />
        <Sep />
        <MetaItem icon="memory" label={`${m.tokenCostK}k Token 消耗`} />
        <Sep />
        <MetaItem icon="verified" label={`综合置信度 ${m.confidencePct}%`} highlight />
      </div>
    </section>
  );
}

interface MetaItemProps {
  icon: string;
  label: string;
  highlight?: boolean;
}

function MetaItem({ icon, label, highlight }: MetaItemProps) {
  return (
    <span className={cn(styles.metaItem, highlight && styles.metaItemHighlight)}>
      <IconSpan name={icon} size={15} />
      {label}
    </span>
  );
}

function Sep() {
  return <span className={styles.metaSep}>·</span>;
}
