"use client";

import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import { Label } from "@/components/ui";
import styles from "./index.module.less";

export interface EmailInputProps {
  id: string;
  label: string;
  placeholder?: string;
}

/**
 * Work-email magic-link input.
 * Includes the absolute-positioned mail icon (top:13px per design alignment)
 * and the right-aligned "发送" submit button (which is also keyboard-handled
 * by page.tsx on Enter).
 */
export function EmailInput({ id, label, placeholder }: EmailInputProps) {
  return (
    <div>
      <Label htmlFor={id} className={styles.label}>
        {label}
      </Label>
      <div className={styles.wrap}>
        <span className={styles.icon}>
          <IconSpan name="mail" size={18} className="text-outline" />
        </span>
        <input
          id={id}
          name="email"
          type="email"
          placeholder={placeholder}
          className={styles.input}
        />
        <button type="submit" className={styles.send}>
          <span className={styles.sendText}>发送</span>
          <IconSpan name="send" size={14} />
        </button>
      </div>
    </div>
  );
}