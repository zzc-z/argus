'use client'

import * as React from 'react'

import { Button, Input, Label } from '@/components/ui'
import { IconSpan } from '@/components/common/IconSpan'
import {
  saveCredentials,
  type CredentialItemV,
  type CredentialsUpdate,
  type CredentialsV,
} from '@/lib/api/settings'

import styles from './index.module.css'

export interface CredentialsPanelProps {
  /** 已加载的凭据状态。null = 还在加载 / 加载失败。 */
  credentials: CredentialsV | null
  /** 重新拉取（保存失败时用）。 */
  onReload: () => void
}

/** 一项凭据的表单字段。 */
interface FieldSpec {
  /** 提交用的键名，与后端 `CredentialsUpdate` 一致。 */
  key: keyof CredentialsUpdate
  label: string
  placeholder: string
  /** 该字段的状态（用于显示「已配置 / 来自部署默认」）。 */
  item?: CredentialItemV
  /** 输入框类型。密钥用 password。 */
  type?: 'text' | 'password'
  /** 提示文字。 */
  hint?: string
  /**
   * 当前生效的值——**非密钥字段**用它预填输入框。
   *
   * 密钥字段不能预填（后端不回显），模型名与端点可以（它们不是秘密）。
   * 预填之后「留空」在界面上就不再是一个需要解释的状态了：用户看到
   * 的就是当前值，改成新值即生效。
   */
  prefill?: string
}

/**
 * 凭据配置表单（design §425-495 的「配置密钥与路由」）。
 *
 * ## 为什么密钥输入框是空的
 *
 * 后端**永不回显密钥内容**（只报「配了没有」与「来自哪一层」）。
 * 所以已配好的 key 在输入框里是空的，状态由输入框下方的标签表示
 * （「已配置」/「部署默认」/「未配置」）。输入框留空 = 不改，
 * 用户填了新值才覆盖。
 *
 * ## 保存语义
 *
 * 只有**用户动过且非空**的字段才提交。空串会被后端忽略（当作没填），
 * 所以「输入框空着 + 没动过」不会把已配好的值清掉。
 */
export function CredentialsPanel({ credentials, onReload }: CredentialsPanelProps) {
  const [values, setValues] = React.useState<Record<string, string>>({})
  // **待清空的字段**——后端用 `null` 表示「清空」，空串只表示「没填」。
  // 不留这个集合的话，用户没法把配错的 key 退回部署默认。
  const [cleared, setCleared] = React.useState<Record<string, boolean>>({})
  const [saving, setSaving] = React.useState(false)
  const [message, setMessage] = React.useState<string | null>(null)
  const [error, setError] = React.useState<string | null>(null)

  const handleChange = React.useCallback((key: string, value: string) => {
    setValues((prev) => ({ ...prev, [key]: value }))
    // 一旦动过这个输入框，「待清空」就不作数了——用户的新值优先。
    setCleared((prev) => {
      if (!prev[key]) return prev
      const next = { ...prev }
      delete next[key]
      return next
    })
    setMessage(null)
    setError(null)
  }, [])

  const handleClear = React.useCallback((key: string) => {
    setCleared((prev) => ({ ...prev, [key]: true }))
    // 清空后输入框也清空——两处状态要一致，否则界面上还显示着旧值。
    setValues((prev) => ({ ...prev, [key]: '' }))
    setMessage(null)
    setError(null)
  }, [])

  const handleSave = React.useCallback(async () => {
    const payload: CredentialsUpdate = {}
    // 先放「待清空」的字段——它们发 null（清空）。
    for (const key of Object.keys(cleared)) {
      payload[key as keyof CredentialsUpdate] = null
    }
    // 再放**被改过且非空**的字段。空串跳过——它表示「用户没动」。
    for (const [key, value] of Object.entries(values)) {
      if (cleared[key]) continue
      if (value.trim().length > 0) {
        payload[key as keyof CredentialsUpdate] = value.trim()
      }
    }

    if (Object.keys(payload).length === 0) {
      setMessage('没有改动')
      return
    }

    setSaving(true)
    setError(null)
    try {
      await saveCredentials(payload)
      setValues({})
      setCleared({})
      setMessage('已保存')
      onReload()
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }, [values, cleared, onReload])

  if (!credentials) {
    return (
      <section className={styles.section} aria-busy="true">
        <p className={styles.hint}>正在加载凭据配置…</p>
      </section>
    )
  }

  const anthropicFields: FieldSpec[] = [
    {
      key: 'anthropic_api_key',
      label: 'API Key',
      placeholder: 'sk-ant-…',
      item: credentials.anthropic_api_key,
      type: 'password',
      hint: '留空表示不改。',
    },
    {
      key: 'anthropic_base_url',
      label: '中转站地址',
      placeholder: 'https://llmapi.pro',
      item: credentials.anthropic_base_url,
      prefill: credentials.anthropic_base_url_value ?? '',
      hint: '留空则用官方端点。',
    },
    {
      key: 'anthropic_complex_model',
      label: '复杂任务模型',
      placeholder: 'claude-sonnet-5',
      prefill: credentials.anthropic_complex_model,
      hint: 'Researcher / Writer / Critic 用它。',
    },
    {
      key: 'anthropic_default_model',
      label: '简单任务模型',
      placeholder: 'claude-haiku-5-5',
      prefill: credentials.anthropic_default_model,
      hint: 'Supervisor / Analyst / Summarizer 用它。',
    },
    {
      key: 'anthropic_critic_model',
      label: 'Critic 模型',
      placeholder: '留空则跟随复杂任务模型',
      prefill: credentials.anthropic_critic_model,
      hint: '引用忠实度判定用的模型。',
    },
  ]

  const tavilyFields: FieldSpec[] = [
    {
      key: 'tavily_api_key',
      label: 'API Key',
      placeholder: 'tvly-…',
      item: credentials.tavily_api_key,
      type: 'password',
      hint: '留空表示不改。',
    },
  ]

  const embeddingFields: FieldSpec[] = [
    {
      key: 'embedding_api_key',
      label: 'API Key',
      placeholder: 'sk-…',
      item: credentials.embedding_api_key,
      type: 'password',
      hint: '留空表示不改。',
    },
    {
      key: 'embedding_base_url',
      label: '兼容端点',
      placeholder: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
      item: credentials.embedding_base_url,
      prefill: credentials.embedding_base_url_value ?? '',
      hint: '留空则用部署默认端点。',
    },
  ]

  return (
    <section className={styles.section}>
      <div className={styles.head}>
        <div className={styles.headLeft}>
          <IconSpan name="key" size={20} className="text-primary-container" />
          <h3 className={`${styles.title} font-headline-sm text-on-surface font-medium`}>
            配置密钥与路由
          </h3>
          <span className={`${styles.tag} font-label-sm text-secondary`}>Credentials</span>
        </div>
      </div>

      <p className={styles.lead}>
        这些配置只对你自己生效，优先级高于部署环境的默认值。密钥保存在本机数据库中，接口不会回显密钥内容。
      </p>

      {credentials.critic_equals_writer && (
        <div className={styles.warning}>
          <IconSpan name="warning" size={16} className="text-on-error-container" />
          <span>
            Critic 与 Writer 用了同一个模型（
            {credentials.anthropic_complex_model}）——LLM
            评委给自己的输出打分会系统性抬高「引用可信」的比例。把下面的「Critic
            模型」改成另一个型号。
          </span>
        </div>
      )}

      <FieldGroup
        title="模型服务（Anthropic）"
        fields={anthropicFields}
        values={values}
        cleared={cleared}
        onChange={handleChange}
        onClear={handleClear}
      />
      <FieldGroup
        title="联网搜索（Tavily）"
        fields={tavilyFields}
        values={values}
        cleared={cleared}
        onChange={handleChange}
        onClear={handleClear}
      />
      <FieldGroup
        title="向量嵌入（Embedding）"
        fields={embeddingFields}
        values={values}
        cleared={cleared}
        onChange={handleChange}
        onClear={handleClear}
      />

      <div className={styles.actions}>
        <Button type="button" onClick={handleSave} disabled={saving}>
          {saving ? '保存中…' : '保存配置'}
        </Button>
        {message && (
          <span role="status" className={styles.ok}>
            {message}
          </span>
        )}
        {error && (
          <span role="alert" className={styles.err}>
            {error}
          </span>
        )}
      </div>
    </section>
  )
}

interface FieldGroupProps {
  title: string
  fields: FieldSpec[]
  values: Record<string, string>
  /** 待清空的字段。 */
  cleared: Record<string, boolean>
  onChange: (key: string, value: string) => void
  onClear: (key: string) => void
}

/** 一组凭据字段。 */
function FieldGroup({ title, fields, values, cleared, onChange, onClear }: FieldGroupProps) {
  return (
    <fieldset className={styles.group}>
      <legend className={`${styles.groupTitle} font-label-sm text-secondary`}>{title}</legend>
      <div className={styles.fields}>
        {fields.map((field) => (
          <Field
            key={field.key}
            spec={field}
            value={values[field.key] ?? field.prefill ?? ''}
            cleared={cleared[field.key] ?? false}
            onChange={onChange}
            onClear={onClear}
          />
        ))}
      </div>
    </fieldset>
  )
}

interface FieldProps {
  spec: FieldSpec
  value: string
  /** 这一项被标记为「待清空」。 */
  cleared: boolean
  onChange: (key: string, value: string) => void
  onClear: (key: string) => void
}

/** 单个字段。 */
function Field({ spec, value, cleared, onChange, onClear }: FieldProps) {
  const inputId = `credential-${spec.key}`
  const hintId = `${inputId}-hint`
  // 「清除」只在**当前值来自用户层**时才有意义——清掉部署默认等于
  // 什么都没清（后端会把 null 当成「回落到部署默认」）。
  const canClear = spec.item?.source === 'user'
  return (
    <div className={styles.field}>
      <Label htmlFor={inputId} className={styles.label}>
        {spec.label}
      </Label>
      <Input
        id={inputId}
        type={spec.type ?? 'text'}
        value={value}
        placeholder={spec.placeholder}
        aria-describedby={hintId}
        disabled={cleared}
        onChange={(e) => onChange(spec.key, e.target.value)}
      />
      <div className={styles.fieldFoot}>
        <span id={hintId} className={`${styles.hint} font-label-sm text-secondary`}>
          {cleared ? '保存后回落到部署默认。' : spec.hint}
        </span>
        <span className={styles.fieldTags}>
          {spec.item && <StatusTag item={spec.item} />}
          {canClear && (
            <button
              type="button"
              className={styles.clear}
              onClick={() => onClear(spec.key)}
              disabled={cleared}
            >
              清除
            </button>
          )}
        </span>
      </div>
    </div>
  )
}

interface StatusTagProps {
  item: CredentialItemV
}

/**
 * 配置状态标签。
 *
 * 三种状态要分清：
 * - `user` —— 你自己配的（绿）
 * - `env`  —— 部署环境里的默认值（灰）
 * - `none` —— 哪儿都没配（琥珀）
 *
 * **只靠颜色不够**（a11y）——文字里也带了状态词。
 */
function StatusTag({ item }: StatusTagProps) {
  if (item.source === 'none') {
    return <span className={`${styles.tagState} ${styles.tagNone} font-label-sm`}>未配置</span>
  }
  if (item.source === 'env') {
    return <span className={`${styles.tagState} ${styles.tagEnv} font-label-sm`}>部署默认</span>
  }
  return <span className={`${styles.tagState} ${styles.tagUser} font-label-sm`}>已配置</span>
}
