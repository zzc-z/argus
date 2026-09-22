"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { IconSpan } from "@/components/common/IconSpan";
import { Toggle } from "../Toggle";
import type { MemoryRule } from "../../mock";
import styles from "./index.module.css";

export interface LongTermMemorySectionProps {
  masterEnabled: boolean;
  crossTopicReasoning: boolean;
  rules: MemoryRule[];
  onMasterChange: (next: boolean) => void;
  onCrossTopicChange: (next: boolean) => void;
  onRuleToggle: (id: string, next: boolean) => void;
  onRuleEdit: (id: string) => void;
  onRuleDelete: (id: string) => void;
  onAddRule: () => void;
}

/**
 * Long-Term Adaptive Memory Control (design §113-252).
 * Master toggle + sub-toggle (cross-topic reasoning) + 3 guiding rule cards.
 * All actions surface `window.confirm` for destructive intent (per design brief:
 * "设置页通常涉及敏感操作,所有按钮加二次确认").
 */
export function LongTermMemorySection({
  masterEnabled,
  crossTopicReasoning,
  rules,
  onMasterChange,
  onCrossTopicChange,
  onRuleToggle,
  onRuleEdit,
  onRuleDelete,
  onAddRule,
}: LongTermMemorySectionProps) {
  const handleDelete = (rule: MemoryRule) => {
    if (typeof window === "undefined") return;
    const ok = window.confirm(
      `确认删除该准则？\n\n${rule.body}\n\n删除后智能体将不再注入该规则。`
    );
    if (ok) onRuleDelete(rule.id);
  };

  const handleAdd = () => {
    if (typeof window === "undefined") {
      onAddRule();
      return;
    }
    const ok = window.confirm("新建一条引导准则？\n\n（Mock：实际页面将打开规则编辑器）");
    if (ok) onAddRule();
  };

  return (
    <section className={styles.section}>
      {/* Header: title + master toggle */}
      <div className={styles.head}>
        <div className={styles.headLeft}>
          <div className={styles.headTitleRow}>
            <IconSpan name="memory" size={22} className="text-primary-container" />
            <h2 className={`${styles.title} font-headline-md font-semibold text-on-surface`}>
              长期自适应记忆控制
            </h2>
            <span className={`${styles.tag} font-label-sm text-secondary`}>
              Long-Term Agent Memory
            </span>
          </div>
          <p className={`${styles.desc} font-body-sm text-secondary`}>
            Argus 智能体集群在多次研报生成与对话交互中沉淀的研究员个人偏好与事实逻辑，自动指导后续研究假设与推导风格。
          </p>
        </div>
        <div className={styles.masterToggle}>
          <div className={styles.masterText}>
            <span className={`${styles.masterLabel} font-label-sm font-medium text-on-surface`}>
              启用长短期记忆图谱
            </span>
            <span className={`${styles.masterSub} font-code text-secondary`}>
              Memory Engine
            </span>
          </div>
          <Toggle
            size="lg"
            checked={masterEnabled}
            onChange={onMasterChange}
            ariaLabel="启用长短期记忆图谱"
          />
        </div>
      </div>

      {/* Sub toggle: cross-topic reasoning */}
      <div className={styles.subToggleRow}>
        <div className={styles.subLeft}>
          <IconSpan name="schema" size={18} className="text-secondary" />
          <div className={styles.subText}>
            <span className={`${styles.subLabel} font-body-sm font-medium text-on-surface`}>
              跨课题上下文联合推理 (Cross-topic reasoning)
            </span>
            <span className={`${styles.subHint} font-label-sm text-secondary`}>
              允许智能体在分析半导体先进制程时引用过往液冷温控算力集群的历史结论
            </span>
          </div>
        </div>
        <Toggle
          size="md"
          checked={crossTopicReasoning}
          onChange={onCrossTopicChange}
          disabled={!masterEnabled}
          ariaLabel="跨课题上下文联合推理"
        />
      </div>

      {/* Rules */}
      <div className={styles.rules}>
        <div className={styles.rulesHead}>
          <span className={`${styles.rulesHeading} font-label-sm uppercase text-secondary`}>
            核心推导准则 · Guiding Rules ({rules.length})
          </span>
          <button type="button" className={styles.addBtn} onClick={handleAdd}>
            <IconSpan name="add" size={14} className="text-primary" />
            <span className={`${styles.addLabel} font-label-sm text-primary`}>新建准则</span>
          </button>
        </div>

        <div className={styles.rulesList}>
          {rules.map((rule) => (
            <article key={rule.id} className={styles.rule}>
              <div className={styles.ruleLeft}>
                <span
                  className={cn(
                    styles.ruleTag,
                    "font-label-sm",
                    rule.tagTone === "primary" && styles.ruleTagPrimary,
                    rule.tagTone === "secondary" && styles.ruleTagSecondary,
                    rule.tagTone === "surface" && styles.ruleTagSurface
                  )}
                >
                  {rule.tag}
                </span>
                <div className={styles.ruleBody}>
                  <p className={`${styles.ruleText} font-body-sm text-on-surface`}>
                    {rule.body}
                  </p>
                  <div className={`${styles.ruleMeta} font-code text-secondary`}>
                    <span>{rule.weightLabel}</span>
                    <span aria-hidden="true">·</span>
                    <span>{rule.scopeLabel}</span>
                  </div>
                </div>
              </div>
              <div className={styles.ruleActions}>
                <Toggle
                  size="sm"
                  checked={rule.enabled}
                  onChange={(next) => onRuleToggle(rule.id, next)}
                  ariaLabel={`启用准则 ${rule.tag}`}
                />
                <button
                  type="button"
                  className={styles.iconBtn}
                  onClick={() => onRuleEdit(rule.id)}
                  title="编辑"
                  aria-label={`编辑准则 ${rule.tag}`}
                >
                  <IconSpan name="edit" size={16} className="text-secondary" />
                </button>
                <button
                  type="button"
                  className={cn(styles.iconBtn, styles.iconBtnDanger)}
                  onClick={() => handleDelete(rule)}
                  title="删除"
                  aria-label={`删除准则 ${rule.tag}`}
                >
                  <IconSpan name="delete" size={16} className="text-secondary" />
                </button>
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
