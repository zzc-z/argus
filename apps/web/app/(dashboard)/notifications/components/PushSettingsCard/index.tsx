import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import type { PushSettings } from '../../mock'
import styles from './index.module.css'

export interface PushSettingsCardProps {
  push: PushSettings
}

/**
 * Right-rail card — push channel overview (Web push / Email / Slack / SMS).
 * 1:1 extracted from argus_notifications/code.html lines 421-478.
 */
export function PushSettingsCard({ push }: PushSettingsCardProps) {
  return (
    <section className={styles.card}>
      <header className={styles.header}>
        <div className={styles.titleWrap}>
          <IconSpan name="notifications_active" size={18} className={styles.titleIcon} />
          <h3 className={styles.title}>推送设置概览</h3>
        </div>
        <a className={styles.configLink} href="#">
          配置信道
        </a>
      </header>

      <div className={styles.channels}>
        {push.channels.map((ch) => (
          <ChannelRow
            key={ch.id}
            icon={ch.icon}
            label={ch.label}
            sub={ch.sub}
            enabled={ch.enabled}
          />
        ))}
      </div>

      <div className={styles.smsRow}>
        <span className={styles.smsLabel}>紧急告警短信通知</span>
        <label className={styles.toggle}>
          <input
            type="checkbox"
            defaultChecked={push.smsAlertEnabled}
            className={styles.toggleInput}
          />
          <span className={styles.toggleTrack} />
        </label>
      </div>
    </section>
  )
}

function ChannelRow({
  icon,
  label,
  sub,
  enabled,
}: {
  icon: string
  label: string
  sub: string
  enabled: boolean
}) {
  return (
    <div className={styles.channel}>
      <div className={styles.channelLeft}>
        <div className={styles.channelIcon}>
          <IconSpan name={icon} size={16} className={styles.channelIconGlyph} />
        </div>
        <div className={styles.channelText}>
          <span className={styles.channelLabel}>{label}</span>
          <span className={styles.channelSub}>{sub}</span>
        </div>
      </div>
      {enabled ? (
        <span className={styles.channelDot} title="已开启" />
      ) : (
        <a className={styles.channelLink} href="#">
          去绑定
        </a>
      )}
    </div>
  )
}
