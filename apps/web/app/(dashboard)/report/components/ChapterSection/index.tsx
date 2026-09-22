"use client";

import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import { CitationMark } from "../CitationMark";
import { cn } from "@/lib/utils";
import type { Chapter } from "../../mock";
import styles from "./index.module.css";

export interface ChapterSectionProps {
  chapter: Chapter;
  /** Look up the surface label for a citation id. */
  citationSurface: (id: string) => string | undefined;
  /** Click a citation to focus the source panel. */
  onCitationClick?: (id: string) => void;
  /** Optional override for the section id (anchor target). */
  anchorId?: string;
  /** Optional children rendered at the bottom (table / charts / cards). */
  children?: React.ReactNode;
}

/**
 * Generic chapter card (SECTION NN). Renders the section header + all blocks
 * (callout / paragraph). Caller supplies table / charts / TCO cards as children.
 */
export function ChapterSection({
  chapter,
  citationSurface,
  onCitationClick,
  anchorId,
  children,
}: ChapterSectionProps) {
  return (
    <section id={anchorId ?? chapter.id} className={styles.card}>
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <span className={cn(styles.badge, "font-code")}>SECTION {chapter.number}</span>
          <h2 className={cn(styles.title, "font-headline-lg")}>{chapter.title}</h2>
        </div>
        {chapter.meta && (
          <span className={cn(styles.meta, "font-label-sm")}>{chapter.meta}</span>
        )}
      </header>

      <div className={styles.body}>
        {chapter.blocks.map((block, idx) => {
          if (block.kind === "callout") {
            return (
              <div key={idx} className={styles.callout}>
                <IconSpan name="auto_awesome" size={22} className="text-primary mt-0.5" />
                <div className={styles.calloutInner}>
                  <span className={cn(styles.calloutHeadline, "font-headline-sm")}>
                    {block.headline}
                  </span>
                  <p className={cn(styles.calloutBody, "font-body-md")}>{block.body}</p>
                </div>
              </div>
            );
          }
          // paragraph
          const citations = block.citationIds ?? [];
          return (
            <p key={idx} className={cn(styles.para, "font-body-lg")}>
              {block.text}
              {citations.map((cid) => {
                const surface = citationSurface(cid);
                if (!surface) return null;
                return (
                  <CitationMark
                    key={cid}
                    surface={surface}
                    onClick={() => onCitationClick?.(cid)}
                  />
                );
              })}
            </p>
          );
        })}

        {children}
      </div>
    </section>
  );
}
