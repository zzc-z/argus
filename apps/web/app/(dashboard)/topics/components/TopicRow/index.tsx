import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import { StatusToggle } from '../StatusToggle'
import { FREQUENCY_OPTIONS, type Frequency, type Topic } from '../../mock'
import styles from './index.module.css'

export type TopicCellKind =
  | 'title'
  | 'sources'
  | 'updated'
  | 'unread'
  | 'frequency'
  | 'status'
  | 'actions'

export interface TopicRowProps {
  topic: Topic
  /** 只渲染某一个 cell —— PlainTable 的 cell 函数每个 column 都会调一次 */
  cellKind: TopicCellKind
  onFrequencyChange: (value: Frequency) => void
  onActiveChange: (active: boolean) => void
}

const SOURCE_ICON_TONE_CLASS: Record<'primary' | 'secondary', string> = {
  primary: 'text-primary',
  secondary: 'text-secondary',
}

/**
 * Per-cell renderer used by TopicTable. Each cell has its own DOM; TopicTable
 * passes `cellKind` so the same component renders whichever column requested it.
 */
export function TopicRow({
  topic,
  cellKind,
  onFrequencyChange,
  onActiveChange,
}: TopicRowProps) {
  switch (cellKind) {
    case 'title':
      return <TitleCell topic={topic} />
    case 'sources':
      return <SourcesCell topic={topic} />
    case 'updated':
      return <UpdatedCell topic={topic} />
    case 'unread':
      return <UnreadCell topic={topic} />
    case 'frequency':
      return (
        <FrequencyCell
          topic={topic}
          onFrequencyChange={onFrequencyChange}
        />
      )
    case 'status':
      return <StatusCell topic={topic} onActiveChange={onActiveChange} />
    case 'actions':
      return <ActionsCell />
  }
}

function TitleCell({ topic }: { topic: Topic }) {
  return (
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
  )
}

function SourcesCell({ topic }: { topic: Topic }) {
  return (
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
  )
}

function UpdatedCell({ topic }: { topic: Topic }) {
  return (
    <div className={styles.updated}>
      <span className={`${styles.updatedTime} font-code`}>{topic.updatedAt}</span>
      <span className={`${styles.updatedDetail} font-label-sm text-secondary`}>
        {topic.updatedDetail}
      </span>
    </div>
  )
}

function UnreadCell({ topic }: { topic: Topic }) {
  return (
    <span className={`${styles.unreadChip} ${unreadToneClass(topic.unreadTone)} font-code`}>
      {topic.unreadLabel}
    </span>
  )
}

function FrequencyCell({
  topic,
  onFrequencyChange,
}: {
  topic: Topic
  onFrequencyChange: (value: Frequency) => void
}) {
  return (
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
  )
}

function StatusCell({
  topic,
  onActiveChange,
}: {
  topic: Topic
  onActiveChange: (active: boolean) => void
}) {
  return (
    <StatusToggle
      checked={topic.active}
      onChange={onActiveChange}
      checkedLabel="运行中"
      uncheckedLabel="已停用"
    />
  )
}

function ActionsCell() {
  return (
    <div className={styles.actionsCell}>
      <button type="button" className={styles.actionBtn} aria-label="管理操作">
        <IconSpan name="more_vert" size={20} />
      </button>
    </div>
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