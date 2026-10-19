'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import styles from './index.module.css'

export interface UrlRssTabsProps {
  /** 提交回调收到**已推导好的 title**，页面上不再让用户填第二次。 */
  onSubmit: (input: { url: string; title: string }) => void
  /** 抓取失败时把原因显示在表单下方。 */
  error?: string | null
  submitting?: boolean
}

/**
 * 从 URL 末段推导一个可读标题。
 *
 * 后端 `SourceCreate.title` 是必填（min_length=1），而这一栏原本只有一个
 * URL 输入框——不给标题就要么让后端报错，要么在前端编一个。所以：从
 * 路径末段取文件名，去掉扩展名与常见噪声字符；取不到就用主机名。
 */
export function deriveTitle(url: string): string {
  try {
    const u = new URL(url)
    const last = u.pathname.split('/').filter(Boolean).pop()
    const base = (last ?? u.hostname).replace(/\.(html?|pdf|txt|md|markdown)$/i, '')
    // 连字符/下划线还原成空格：arxiv 的 slug 全是小写连字符，直接当标题太难读
    const pretty = base.replace(/[-_]+/g, ' ').trim()
    return (pretty || u.hostname).slice(0, 120)
  } catch {
    return url.slice(0, 120)
  }
}

export function UrlRssTabs({ onSubmit, error, submitting }: UrlRssTabsProps) {
  const [urlValue, setUrlValue] = React.useState('')
  const [titleValue, setTitleValue] = React.useState('')
  // 用户手改过标题就别再自动覆盖——「以最后一次输入为准」优先于便利性。
  const [titleTouched, setTitleTouched] = React.useState(false)

  const onUrlChange = (raw: string) => {
    setUrlValue(raw)
    if (!titleTouched) setTitleValue(deriveTitle(raw))
  }

  const canSubmit = urlValue.trim().length > 0 && titleValue.trim().length > 0 && !submitting

  const submit = () => {
    if (!canSubmit) return
    onSubmit({ url: urlValue.trim(), title: titleValue.trim() })
  }

  return (
    <section className={styles.section} aria-label="从网址导入">
      <div className={styles.head}>
        <span className={`${styles.headTitle} font-label-sm uppercase tracking-wider`}>
          网址导入 From URL
        </span>
      </div>
      <div className={styles.urlRow}>
        <div className={styles.urlInputWrap}>
          <span className={styles.urlIcon}>
            <IconSpan name="link" size={18} className="text-secondary" />
          </span>
          <input
            type="url"
            value={urlValue}
            onChange={(e) => onUrlChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') submit()
            }}
            className={`${styles.urlInput} font-body-sm`}
            placeholder="https://arxiv.org/abs/2403... 或任意新闻研报地址"
            aria-label="资料网址"
            data-testid="url-input"
          />
        </div>
        <button
          type="button"
          onClick={submit}
          disabled={!canSubmit}
          className={`${styles.fetchBtn} font-body-sm`}
          data-testid="url-submit"
        >
          <IconSpan name="downloading" size={18} />
          <span>{submitting ? '提交中…' : '抓取并解析'}</span>
        </button>
      </div>
      {urlValue.trim() && (
        <div className={styles.urlRow}>
          <label className={styles.titleLabel}>
            <span className={`${styles.titleHint} font-body-sm`}>
              资料名称（默认取自网址，可改）
            </span>
            <input
              type="text"
              value={titleValue}
              onChange={(e) => {
                setTitleTouched(true)
                setTitleValue(e.target.value)
              }}
              className={`${styles.urlInput} ${styles.titleInput} font-body-sm`}
              aria-label="资料名称"
              data-testid="url-title"
            />
          </label>
        </div>
      )}
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
    </section>
  )
}
