"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import styles from "./index.module.css";

export interface CitationMarkProps {
  /** Surface label, e.g. "1". */
  surface: string;
  /** Optional click handler — wired by parent (e.g. open SourcesPanel). */
  onClick?: () => void;
  className?: string;
}

/**
 * Inline superscript citation mark (renders the "[N]" badges embedded inside
 * chapter paragraphs). Pure presentation; parent owns the citation lookup map.
 */
export function CitationMark({ surface, onClick, className }: CitationMarkProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(styles.mark, "font-code", className)}
      aria-label={`引用 ${surface}`}
    >
      {surface}
    </button>
  );
}
