import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import { StatusToggle } from '../StatusToggle'
import { FREQUENCY_OPTIONS, type Frequency, type Topic } from '../../mock'
import styles from './index.module.css'

export interface TopicRowProps {
  topic: Topic
  checked: boolean
  onCheck: () => void
  onFrequencyChange: (value: Frequency) => void
  onActiveChange: (active: boolean) => void
}

const SOURCE_ICON_TONE_CLASS: Record<'primary' | 'secondary', string> = {
  primary: 'text-primary',
  secondary: 'text-secondary',
}

/**
 * One subscription row in the table.
 *
 * - First column: checkbox.
 * - Title cell: link + category chip + 2-line description + agent footer line.
 * - Source cell: chips stack of icon + label (wraps when narrow).
 * - Updated / Unread / Frequency / Status / Actions columns mirror the design 1:1.
 *
 * Paused rows render at 75% opacity (per `argus_topics/code.html` row 5), with
 * full opacity on hover and a disabled frequency select.
 */
export function TopicRow({
  topic,
  checked,
  onCheck,
  onFrequencyChange,
  onActiveChange,
}: TopicRowProps) {
  const rowClass = `${styles.row} ${topic.active ? '' : styles.rowPaused}`

  return (
    <tr className={rowClass}>
      <td className={styles.td}>
        <input
          type="checkbox"
          aria-label={`选择 ${topic.title}`}
          className={styles.checkbox}
          checked={checked}
          onChange={onCheck}
        />
      </td>

      <td className={styles.td}>
        <div className={styles.titleBlock}>
          <div className={styles.titleLine}>
            <a href="#" className={`${styles.titleLink} font-headline-sm font-semibold`}>
              {topic.title}
            </a>
            <span
              className={`${styles.categoryChip} font-label-sm ${
                topic.active ? '' : styles.categoryChipPaused
              }`}
            >
              {topic.category}
            </span>
          </div>
          <p className={`${styles.description} font-body-sm text-secondary`}>{topic.description}</p>
          <div className={`${styles.meta} text-secondary`}>
            <span className={`${styles.metaItem} font-code`}>
              <IconSpan
                name={topic.active ? 'psychology' : 'pause_circle'}
                size={14}
                className={topic.active ? 'text-primary' : 'text-secondary'}
              />
              Agent: {topic.agent}
            </span>
            {topic.deepFilter && (
              <>
                <span className={styles.metaSep}>·</span>
                <span className={`${styles.metaItem} font-code`}>深度置信过滤开启</span>
              </>
            )}
          </div>
        </div>
      </td>

      <td className={styles.td}>
        <div className={styles.sources}>
          {topic.sources.map((src, i) => (
            <span key={`${topic.id}-src-${i}`} className={styles.sourceChip} title={src.hint}>
              <IconSpan
                name={src.icon}
                size={13}
                className={src.iconTone ? SOURCE_ICON_TONE_CLASS[src.iconTone] : 'text-secondary'}
              />
              {src.label}
            </span>
          ))}
        </div>
      </td>

      <td className={styles.td}>
        <div className={styles.updated}>
          <span className={`${styles.updatedTime} font-code`}>{topic.updatedAt}</span>
          <span className={`${styles.updatedDetail} font-label-sm text-secondary`}>
            {topic.updatedDetail}
          </span>
        </div>
      </td>

      <td className={styles.td}>
        <span className={`${styles.unreadChip} ${unreadToneClass(topic.unreadTone)} font-code`}>
          {topic.unreadLabel}
        </span>
      </td>

      <td className={styles.td}>
        <div className={styles.freqWrap}>
          <select
            aria-label={`更新频率 ${topic.title}`}
            value={topic.frequency}
            onChange={(e) => onFrequencyChange(e.target.value as Frequency)}
            disabled={!topic.active}
            className={`${styles.freqSelect} font-code ${topic.active ? '' : styles.freqSelectPaused}`}
          >
            {FREQUENCY_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <IconSpan
            name="expand_more"
            size={16}
            className={`${styles.freqCaret} ${topic.active ? '' : styles.freqCaretPaused}`}
          />
        </div>
      </td>

      <td className={styles.td}>
        <StatusToggle
          checked={topic.active}
          onChange={onActiveChange}
          checkedLabel="运行中"
          uncheckedLabel="已停用"
        />
      </td>

      <td className={`${styles.td} ${styles.actionsCell}`}>
        <button type="button" className={styles.actionBtn} aria-label="管理操作">
          <IconSpan name="more_vert" size={20} />
        </button>
      </td>
    </tr>
  )
}

function unreadToneClass(tone: Topic['unreadTone']): string {
  // Fallback to a concrete class because `.module.css` access is
  // `string | undefined` under noUncheckedIndexedAccess.
  const fallback = styles.unreadMuted ?? ''
  switch (tone) {
    case 'primary':
      return styles.unreadPrimary ?? fallback
    case 'secondary':
      return styles.unreadSecondary ?? fallback
    case 'muted':
    default:
      return fallback
  }
}
