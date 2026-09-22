"use client";

import * as React from "react";
import { useState, useEffect, useRef } from "react";
import { IconSpan } from "@/components/common/IconSpan";
import {
  type TypeFilterValue,
  type ViewMode,
  typeOptions,
  viewModes,
} from "../../mock";
import styles from "./index.module.css";

export interface FilterToolbarProps {
  unreadCount: number;
  totalCount: number;
  statusFilter: "unread" | "all";
  typeFilter: TypeFilterValue;
  viewMode: ViewMode;
  onStatusChange: (s: "unread" | "all") => void;
  onTypeChange: (t: TypeFilterValue) => void;
  onViewModeChange: (m: ViewMode) => void;
}

/**
 * Status tabs + type dropdown + view-mode toggle.
 * 1:1 extracted from argus_notifications/code.html lines 37-80.
 *
 * Dropdown open/close is local state; everything else is props-driven.
 * Outside-click closes the dropdown (mirrors the design's vanilla JS).
 */
export function FilterToolbar(props: FilterToolbarProps) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("click", onDoc);
    return () => document.removeEventListener("click", onDoc);
  }, [open]);

  const currentType = typeOptions.find((o) => o.value === props.typeFilter) ?? typeOptions[0];

  return (
    <div className={styles.bar}>
      <div className={styles.left}>
        <div className={styles.tabs}>
          <button
            type="button"
            className={props.statusFilter === "unread" ? styles.tabActive : styles.tab}
            onClick={() => props.onStatusChange("unread")}
          >
            <span>未读通知</span>
            <span
              className={
                props.statusFilter === "unread" ? styles.tabBadgeActive : styles.tabBadge
              }
            >
              {props.unreadCount}
            </span>
          </button>
          <button
            type="button"
            className={props.statusFilter === "all" ? styles.tabActive : styles.tab}
            onClick={() => props.onStatusChange("all")}
          >
            <span>全部历史</span>
            <span
              className={
                props.statusFilter === "all" ? styles.tabBadgeActive : styles.tabBadge
              }
            >
              {props.totalCount}
            </span>
          </button>
        </div>

        <div className={styles.dropdownWrap} ref={wrapRef}>
          <button
            type="button"
            className={styles.dropdownBtn}
            onClick={(e) => {
              e.stopPropagation();
              setOpen((v) => !v);
            }}
          >
            <IconSpan name="filter_list" size={16} className={styles.dropdownIcon} />
            <span>{currentType.label}</span>
            <IconSpan name="expand_more" size={16} className={styles.dropdownIcon} />
          </button>
          {open && (
            <div className={styles.dropdownMenu} role="menu">
              {typeOptions.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  className={
                    opt.value === props.typeFilter ? styles.optionActive : styles.option
                  }
                  onClick={() => {
                    props.onTypeChange(opt.value);
                    setOpen(false);
                  }}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className={styles.right}>
        <span className={`${styles.viewLabel} font-label-sm uppercase`}>视图模式</span>
        <div className={styles.viewTabs}>
          {viewModes.map((m) => (
            <button
              key={m.value}
              type="button"
              className={props.viewMode === m.value ? styles.viewTabActive : styles.viewTab}
              onClick={() => props.onViewModeChange(m.value)}
            >
              <IconSpan name={m.icon} size={15} />
              <span>{m.label}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}