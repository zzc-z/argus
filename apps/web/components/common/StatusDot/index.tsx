import * as React from "react";
import { cn } from "@/lib/utils";
import styles from "./index.module.less";

export type StatusDotColor = "emerald" | "purple" | "amber" | "rose";

export interface StatusDotProps {
  color?: StatusDotColor;
  ping?: boolean;
  className?: string;
}

/**
 * Animated status dot for live indicators (probe health, agent activity).
 * When `ping` is true, emits an outer ring ping animation (typical for live).
 */
export function StatusDot({ color = "emerald", ping = false, className }: StatusDotProps) {
  const dotClass = styles[color] ?? styles.emerald;
  return (
    <span className={cn(styles.wrap, className)}>
      {ping && <span className={cn(styles.ping, dotClass)} aria-hidden="true" />}
      <span className={cn(styles.dot, dotClass)} />
    </span>
  );
}