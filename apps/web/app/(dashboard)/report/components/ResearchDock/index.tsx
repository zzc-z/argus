"use client";

import * as React from "react";
import { useState } from "react";
import { IconSpan } from "@/components/common/IconSpan";
import { cn } from "@/lib/utils";
import styles from "./index.module.css";

const DOCK_PLACEHOLDER =
  "针对本篇研报提问，或指示智能体进一步推演（例如：测算在 512k 极端长文本下的显存溢出概率）...";

/**
 * Bottom floating "research query" dock — pinned above the report body so the
 * user can always ask follow-ups without scrolling. Self-contained:
 *   - local input state (the page is otherwise purely presentation)
 *   - submit is a no-op (placeholder; real handler plumbed via props later)
 */
export function ResearchDock() {
  const [draft, setDraft] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    // no-op: real handler plumbed when the API lands
    setDraft("");
  };

  return (
    <div className={styles.dock}>
      <form className={styles.bar} onSubmit={handleSubmit}>
        <div className={styles.avatar}>
          <IconSpan name="smart_toy" size={18} />
        </div>
        <input
          className={cn(styles.input, "font-body-sm")}
          type="text"
          placeholder={DOCK_PLACEHOLDER}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          aria-label="针对本篇研报提问"
        />
        <div className={styles.toolbar}>
          <IconBtn name="attach_file" title="添加附加资料" />
          <IconBtn name="mic" title="语音输入" />
          <button
            type="submit"
            className={cn(styles.submitBtn, "font-headline-sm")}
          >
            <span>继续推演</span>
            <IconSpan name="arrow_upward" size={16} />
          </button>
        </div>
      </form>
    </div>
  );
}

interface IconBtnProps {
  name: string;
  title: string;
}

function IconBtn({ name, title }: IconBtnProps) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      className={styles.toolBtn}
    >
      <IconSpan name={name} size={18} />
    </button>
  );
}
