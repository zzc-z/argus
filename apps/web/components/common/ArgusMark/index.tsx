import * as React from "react";
import styles from "./index.module.less";

/**
 * Argus precise vector mark — 1:1 extracted from argus_3/code.html.
 * Public component (cross-page). Color follows `currentColor` so callers
 * can theme it via Tailwind `text-*` utilities.
 */
export interface ArgusMarkProps extends React.SVGProps<SVGSVGElement> {
  size?: number;
}

export function ArgusMark({ size = 20, className, ...props }: ArgusMarkProps) {
  return (
    <span className={`${styles.shell} ${className ?? ""}`}>
      <svg
        className={styles.svg}
        fill="none"
        viewBox="0 0 24 24"
        xmlns="http://www.w3.org/2000/svg"
        width={size}
        height={size}
        {...props}
      >
        <circle
          className={styles.ringOuter}
          cx="12"
          cy="12"
          r="9"
          stroke="currentColor"
          strokeWidth="1.75"
        />
        <path
          d="M12 3C7.02944 3 3 7.02944 3 12C3 16.9706 7.02944 20 12 20"
          stroke="currentColor"
          strokeLinecap="round"
          strokeWidth="2"
        />
        <circle
          cx="12"
          cy="12"
          r="4.25"
          fill="#ffffff"
          stroke="currentColor"
          strokeWidth="1.75"
        />
        <circle cx="12" cy="12" fill="currentColor" r="2" />
        <path
          className={styles.crosshair}
          d="M12 7.75V3M21 12H16.25M12 21v-4.75M3 12h4.75"
          stroke="currentColor"
          strokeLinecap="round"
          strokeWidth="1.5"
        />
      </svg>
    </span>
  );
}