"use client";

import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import { cn } from "@/lib/utils";
import { type ViewKey, viewTabs } from "../../mock";
import styles from "./index.module.css";

export interface ViewSwitcherProps {
  value: ViewKey;
  onChange: (key: ViewKey) => void;
}

/**
 * 4-tab multimodal view switcher (Report / Comparison Table / Timeline / Decision).
 * Pure controlled component — parent owns the active tab.
 */
export function ViewSwitcher({ value, onChange }: ViewSwitcherProps) {
  return (
    <div className={styles.bar}>
      <div className={styles.tabs}>
        {viewTabs.map((tab) => {
          const active = tab.key === value;
          return (
            <button
              key={tab.key}
              type="button"
              onClick={() => onChange(tab.key)}
              className={cn(styles.tab, "font-headline-sm", active && styles.activeTab)}
              aria-pressed={active}
            >
              <IconSpan
                name={tab.icon}
                size={18}
                className={cn(active ? "text-primary" : "")}
              />
              <span>{tab.label}</span>
              {active && <span className={styles.activeDot} aria-hidden="true" />}
            </button>
          );
        })}
      </div>
      <div className={styles.modeMeta}>
        <span className={cn(styles.modeLabel, "font-code")}>模式：学术研判 V3.8</span>
        <button type="button" className={styles.expandBtn} aria-label="展开">
          <IconSpan name="open_in_full" size={18} />
        </button>
      </div>
    </div>
  );
}
