"use client";

import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import { Button } from "@/components/ui";
import { profileBanner } from "../../mock";
import styles from "./index.module.css";

export interface ProfileBannerProps {
  onManageProfile: () => void;
  onSyncSso: () => void;
}

/**
 * Profile snippet banner (design §84-112).
 * Top of the right panel: avatar + name + role + email + 2 actions.
 */
export function ProfileBanner({ onManageProfile, onSyncSso }: ProfileBannerProps) {
  const { name, roleTag, email, emailVerifiedTag, primaryAction, secondaryAction } =
    profileBanner;

  return (
    <div className={styles.card}>
      <div className={styles.left}>
        <div className={styles.avatar} aria-hidden="true">
          <IconSpan name="person" size={24} className="text-on-primary" />
        </div>
        <div className={styles.identity}>
          <div className={styles.nameRow}>
            <span className={`${styles.name} font-headline-sm font-medium text-on-surface`}>
              {name}
            </span>
            <span
              className={`${styles.roleTag} font-label-sm text-on-primary-fixed-variant`}
            >
              {roleTag}
            </span>
          </div>
          <div className={styles.metaRow}>
            <span className={`${styles.email} font-code text-secondary`}>{email}</span>
            <span className={`${styles.emailTag} font-label-sm text-on-surface-variant`}>
              {emailVerifiedTag}
            </span>
          </div>
        </div>
      </div>
      <div className={styles.actions}>
        <Button
          variant="secondary"
          size="sm"
          onClick={onManageProfile}
          className={styles.actionSecondary}
        >
          <IconSpan name={primaryAction.icon} size={16} />
          <span>{primaryAction.label}</span>
        </Button>
        <Button
          variant="default"
          size="sm"
          onClick={onSyncSso}
          className={styles.actionPrimary}
        >
          <IconSpan name={secondaryAction.icon} size={16} />
          <span>{secondaryAction.label}</span>
        </Button>
      </div>
    </div>
  );
}
