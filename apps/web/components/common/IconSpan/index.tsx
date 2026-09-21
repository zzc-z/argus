import * as React from "react";
import styles from "./index.module.css";

/**
 * Material Symbols Outlined icon wrapper.
 *
 * Rule (AGENTS.md §13):
 *   - Must force `fontSize` via inline style — Tailwind text-[Npx] is unreliable
 *     across `(auth)` route group + arbitrary value scanning.
 *   - Icon name MUST exist in Google Material Symbols Outlined catalog.
 *   - No custom SVG / emoji / lucide-react — see §13.
 */
export type IconSize = 13 | 14 | 15 | 16 | 18 | 20 | 22 | 24;

export interface IconSpanProps {
  name: string;
  size?: IconSize;
  className?: string;
  style?: React.CSSProperties;
  "aria-label"?: string;
}

export function IconSpan({
  name,
  size = 16,
  className,
  style,
  "aria-label": ariaLabel,
}: IconSpanProps) {
  return (
    <span
      role={ariaLabel ? "img" : undefined}
      aria-label={ariaLabel}
      aria-hidden={ariaLabel ? undefined : true}
      className={`material-symbols-outlined ${className ?? ""}`}
      style={{ fontSize: `${size}px`, ...style }}
    >
      {name}
    </span>
  );
}