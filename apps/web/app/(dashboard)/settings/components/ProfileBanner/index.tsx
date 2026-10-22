'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import { Button } from '@/components/ui'
import type { ProfileBannerData } from '../../view'
import styles from './index.module.css'

export interface ProfileBannerProps {
  /** 用户资料。null = 还没加载出来。 */
  profile: ProfileBannerData | null
  onManageProfile: () => void
  onSyncSso: () => void
}

/**
 * Profile snippet banner (design §84-112).
 * Top of the right panel: avatar + name + role + email + 2 actions.
 *
 * 内容来自 `GET /api/v1/me`（由全局 UserContext 拉取，映射见 `view.ts`）。
 */
export function ProfileBanner({ profile, onManageProfile, onSyncSso }: ProfileBannerProps) {
  if (!profile) {
    return (
      <div className={styles.card} aria-busy="true">
        <div className={styles.left}>
          <div className={styles.avatar} aria-hidden="true">
            <IconSpan name="person" size={24} className="text-on-primary" />
          </div>
          <div className={styles.identity}>
            <div className={styles.nameRow}>
              <span className={`${styles.name} font-headline-sm text-on-surface font-medium`}>
                正在加载资料…
              </span>
            </div>
          </div>
        </div>
      </div>
    )
  }

  const { name, roleTag, email, emailVerifiedTag, primaryAction, secondaryAction } = profile

  return (
    <div className={styles.card}>
      <div className={styles.left}>
        <div className={styles.avatar} aria-hidden="true">
          <IconSpan name="person" size={24} className="text-on-primary" />
        </div>
        <div className={styles.identity}>
          <div className={styles.nameRow}>
            <span className={`${styles.name} font-headline-sm text-on-surface font-medium`}>
              {name}
            </span>
            <span className={`${styles.roleTag} font-label-sm text-on-primary-fixed-variant`}>
              {roleTag}
            </span>
          </div>
          <div className={styles.metaRow}>
            <span className={`${styles.email} font-code text-secondary`}>{email}</span>
            <span className={`${styles.emailVerifiedTag} font-label-sm text-on-surface-variant`}>
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
        <Button variant="default" size="sm" onClick={onSyncSso} className={styles.actionPrimary}>
          <IconSpan name={secondaryAction.icon} size={16} />
          <span>{secondaryAction.label}</span>
        </Button>
      </div>
    </div>
  )
}
