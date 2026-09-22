import * as React from "react";
import styles from "./index.module.css";

/**
 * Visual DAG topology fault diagram — root, planner, vector, critic (suspended), synthesizer, destination.
 * Pure SVG mirroring the argus_error_404_500 design 1:1.
 * Colors follow Tailwind 47 tokens (fill-*, stroke-* + text-* utility classes).
 */
export function TopologyDiagram() {
  return (
    <div className={styles.wrap}>
      <svg
        className={styles.svg}
        viewBox="0 0 400 120"
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        aria-hidden="true"
      >
        {/* Connecting links (healthy) */}
        <line
          className="stroke-surface-container-highest"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeDasharray="3 3"
          x1="80"
          x2="160"
          y1="60"
          y2="35"
        />
        <line
          className="stroke-surface-container-highest"
          stroke="currentColor"
          strokeWidth="1.5"
          x1="80"
          x2="160"
          y1="60"
          y2="85"
        />
        <line
          className="stroke-surface-container-highest"
          stroke="currentColor"
          strokeWidth="1.5"
          x1="160"
          x2="240"
          y1="85"
          y2="85"
        />
        <line
          className="stroke-surface-container-highest"
          stroke="currentColor"
          strokeWidth="1.5"
          x1="160"
          x2="240"
          y1="35"
          y2="35"
        />

        {/* Fault link (interrupted) */}
        <path
          className={styles.faultLink}
          d="M 240 35 L 320 60"
          stroke="#ba1a1a"
          strokeWidth="1.5"
          strokeDasharray="4 4"
        />

        {/* Recovery link */}
        <line
          className="stroke-primary-container"
          stroke="currentColor"
          strokeWidth="1.5"
          x1="240"
          x2="320"
          y1="85"
          y2="60"
        />

        {/* ROOT */}
        <circle
          className="fill-surface-container-lowest stroke-secondary"
          cx="80"
          cy="60"
          r="14"
          strokeWidth="1.5"
        />
        <text
          className="font-code fill-secondary"
          textAnchor="middle"
          x="80"
          y="64"
          fontSize="10"
        >
          ROOT
        </text>

        {/* PLAN */}
        <circle
          className="fill-surface-container-lowest stroke-primary"
          cx="160"
          cy="35"
          r="14"
          strokeWidth="1.5"
        />
        <text
          className="font-code fill-primary"
          textAnchor="middle"
          x="160"
          y="39"
          fontSize="9"
        >
          PLAN
        </text>

        {/* VEC */}
        <circle
          className="fill-surface-container-lowest stroke-secondary"
          cx="160"
          cy="85"
          r="14"
          strokeWidth="1.5"
        />
        <text
          className="font-code fill-secondary"
          textAnchor="middle"
          x="160"
          y="89"
          fontSize="9"
        >
          VEC
        </text>

        {/* CRITIC (suspended — fault node) */}
        <circle
          className="fill-error-container stroke-error"
          cx="240"
          cy="35"
          r="16"
          strokeWidth="1.5"
        />
        <text
          className="font-code fill-error font-medium"
          textAnchor="middle"
          x="240"
          y="39"
          fontSize="9"
        >
          CRITIC
        </text>

        {/* SYN */}
        <circle
          className="fill-surface-container-lowest stroke-secondary"
          cx="240"
          cy="85"
          r="14"
          strokeWidth="1.5"
        />
        <text
          className="font-code fill-secondary"
          textAnchor="middle"
          x="240"
          y="89"
          fontSize="9"
        >
          SYN
        </text>

        {/* DEST (unreachable) */}
        <circle
          className="fill-surface-container stroke-outline"
          cx="320"
          cy="60"
          r="14"
          strokeWidth="1.5"
          strokeDasharray="2 2"
        />
        <text
          className="font-code fill-outline"
          textAnchor="middle"
          x="320"
          y="64"
          fontSize="9"
        >
          DEST
        </text>

        {/* Ping radar over fault node */}
        <circle
          className={styles.radar}
          cx="240"
          cy="35"
          r="22"
          stroke="#7039f9"
          strokeWidth="1"
          fill="none"
        />
      </svg>
    </div>
  );
}
