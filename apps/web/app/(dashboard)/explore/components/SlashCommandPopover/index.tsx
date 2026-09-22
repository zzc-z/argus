"use client";

import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import { SLASH_COMMANDS, type SlashCommand } from "../../mock";
import styles from "./index.module.css";

export interface SlashCommandPopoverProps {
  visible: boolean;
  onSelect: (cmd: SlashCommand) => void;
}

/**
 * Slash command popover shown above the prompt input when the user types "/".
 * Selecting an entry inserts the command text into the input (handled by parent).
 */
export function SlashCommandPopover({ visible, onSelect }: SlashCommandPopoverProps) {
  if (!visible) return null;

  return (
    <div className={styles.popover} role="listbox">
      <div className={styles.head}>
        <IconSpan name="bolt" size={13} className={styles.headIcon} />
        <span>智能体指令 (Agent Commands)</span>
      </div>
      {SLASH_COMMANDS.map((c) => (
        <button
          key={c.cmd}
          type="button"
          className={styles.row}
          onClick={() => onSelect(c)}
        >
          <div className={styles.rowLeft}>
            <span className={styles.rowCmd}>{c.cmd}</span>
            <span className={styles.rowDesc}>{c.description}</span>
          </div>
          <span className={styles.rowHint}>Tab</span>
        </button>
      ))}
    </div>
  );
}
