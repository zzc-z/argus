import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import { TONE, type Tone } from './tone'
import styles from './cells.module.css'

export interface AvatarProps {
  /** Material icon name */
  icon: string
  /** iconTile 背景 + icon 颜色的语义 tone（必填） */
  iconTone: Tone
  /** 主标题 */
  title: React.ReactNode
  /** 副标题（可选） */
  subtitle?: React.ReactNode
  /** 给标题套 <a> 的 href；不传则渲染为 span */
  href?: string
  /** 标题样式 variant：'link'（默认，hover 变紫）/ 'plain' */
  titleVariant?: 'link' | 'plain'
  /** 标题额外 className（如 font-semibold） */
  titleClassName?: string
  /** 副标题额外 className（如 font-code） */
  subtitleClassName?: string
}

/**
 * Avatar —— iconTile + 标题链 + 副标题
 *  - 用于 sources 资料名称与来源描述、topics 课题名称与描述等带图标 + 标题 + 副标题的 cell
 */
export function Avatar({
  icon,
  iconTone,
  title,
  subtitle,
  href,
  titleVariant = 'link',
  titleClassName,
  subtitleClassName,
}: AvatarProps) {
  const tone = TONE[iconTone]
  const titleCls =
    titleVariant === 'link' ? styles.titleLink : styles.titlePlain
  const titleEl = href ? (
    <a href={href} className={`${titleCls} ${titleClassName ?? ''}`}>
      {title}
    </a>
  ) : (
    <span className={`${titleCls} ${titleClassName ?? ''}`}>{title}</span>
  )

  return (
    <div className={styles.avatarInner}>
      <div className={`${styles.iconTile} ${styles[tone.iconTileBg]} ${styles[tone.iconTileText]}`}>
        <IconSpan name={icon} size={18} />
      </div>
      <div className={styles.avatarText}>
        {titleEl}
        {subtitle !== undefined && subtitle !== null && (
          <span className={`${styles.meta} ${subtitleClassName ?? ''}`}>{subtitle}</span>
        )}
      </div>
    </div>
  )
}