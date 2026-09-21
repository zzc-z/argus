import * as React from "react";
import { cn } from "@/lib/utils";
import styles from "./index.module.css";

export type KbdHintTone = "dark" | "light";

export interface KbdHintProps extends React.HTMLAttributes<HTMLSpanElement> {
  /** Keyboard shortcut text, e.g. "⌘G". */
  children: React.ReactNode;
  tone?: KbdHintTone;
}

/**
 * Keyboard shortcut micro-badge, e.g. ⌘G / ⌘W.
 * Tone=dark renders on the dark OAuth button (neutral-800 bg),
 * tone=light renders on the light OAuth button (surface-container bg).
 */
export function KbdHint({ children, tone = "dark", className, ...props }: KbdHintProps) {
  return (
    <span
      className={cn(
        styles.kbd,
        tone === "dark" ? styles.dark : styles.light,
        "font-code",
        className
      )}
      {...props}
    >
      {children}
    </span>
  );
}