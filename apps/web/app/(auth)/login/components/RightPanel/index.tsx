import * as React from "react";
import { ProbeStatusBar } from "../ProbeStatusBar";
import { DagCardGrid } from "../DagCardGrid";
import { Testimonial } from "../Testimonial";
import styles from "./index.module.less";

/**
 * Right column of the login page — ambient tech visualization showcase.
 * Dark theme surface (per design intent); atmosphere + telemetry + DAG + testimonial.
 */
export function RightPanel() {
  return (
    <aside className={styles.root}>
      {/* Atmospheric ambient glows + tech-grid background */}
      <div className={styles.gridPattern} aria-hidden="true" />
      <div className={`${styles.glow} ${styles.glowTop}`} aria-hidden="true" />
      <div className={`${styles.glow} ${styles.glowBottom}`} aria-hidden="true" />

      <ProbeStatusBar />
      <DagCardGrid />
      <Testimonial />
    </aside>
  );
}