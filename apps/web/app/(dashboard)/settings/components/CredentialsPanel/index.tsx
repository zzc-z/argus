'use client'

import { useState } from 'react'

import { Button, Input, Label } from '@/components/ui'
import { IconSpan } from '@/components/common/IconSpan'
import { saveCredentials, type CredentialsUpdate } from '@/lib/api/settings'

import type { CredentialsState } from '../../useCredentials'

import styles from './index.module.css'

export interface CredentialsPanelProps {
  /**
   * 面板要渲染的凭据状态。
   *
   * 三态分开给（见 `useCredentials`）：加载中显示占位，出错显示重试入口，
   * 有数据显示表单。**重拉期间保持 `ready`**——面板不闪回加载态。
   */
  state: CredentialsState
  /** 重新拉取。 */
  onReload: () => void
  /** 保存成功时通知父组件弹提示。 */
  onSaved: () => void
  /** 没有任何改动时通知父组件（弹一句提示，而不是静默）。 */
  onNothingChanged: () => void
  /** 保存失败时通知父组件弹错误提示。 */
  onSaveFailed: (message: string) => void
}

/**
 * key 字段 → 它配对的 base_url 字段。
 *
 * 后端要求两者成对（见 ``services/credentials.py`` 的 ``_pair``）：
 * 用户层只存 key 不存 url，那把 key 会走官方端点。
 */
const PAIRED_URL_FIELD: Record<string, string> = {
  anthropic_api_key: 'anthropic_base_url',
  embedding_api_key: 'embedding_base_url',
}

/** 一项凭据的表单字段。 */
interface FieldSpec {
  /** 提交用的键名，与后端 `CredentialsUpdate` 一致。 */
  key: keyof CredentialsUpdate
  label: string
  placeholder: string
  /** 输入框类型。密钥用 password（配眼睛图标切明文）。 */
  type?: 'text' | 'password'
  /**
   * 预填的值是**占位串**（不是真值）——后端标明了 `masked_key_fields`。
   *
   * 占位串**绝不能进 payload**：用户碰一下输入框，`••••••••abcd` 就被
   * 提交，后端会加密存成用户的 key——之后每次调用都用这把假 key，
   * 401 且界面显示「已配置」，用户完全看不出哪里错了。
   *
   * 这类输入框获得焦点时清空、失焦仍为空时恢复占位串——用户只能整把
   * 填新 key（覆盖默认值），不会在占位串上改出半截假 key。
   * 万一值里仍含 `•`，提交时也会跳过（见 handleSave）。
   */
  masked?: boolean
  /** 提示文字。 */
  hint?: string
  /**
   * 当前生效的值——用它预填输入框。
   *
   * **密钥也预填**：后端回显当前生效的 key，用户看得见自己配的是
   * 什么、默认的是什么。预填之后「留空 = 不改」在界面上就不再是
   * 一个需要解释的状态了——用户看到的就是当前值，改成新值即生效。
   */
  prefill?: string
}

/**
 * 凭据配置表单（design §425-495 的「配置密钥与路由」）。
 *
 * ## 为什么输入框里已经填着内容
 *
 * 后端回显**当前生效的值**（含密钥）——用户看得见自己配的是什么、
 * 默认的是什么。输入框里**有内容就是配好了**，这是大众用户最直白的
 * 判断方式。
 *
 * 额外再挂一个「已配置 / 部署默认」的标签只是把同一件事说两遍，
 * 而且标签写的是**来源**（用户层还是部署层），那是运维视角。
 *
 * ## 保存语义
 *
 * **只有用户动过的字段才提交。** 输入框留空 = 不改（后端把空串当
 * 「没填」忽略）。改成新值即生效。
 */
export function CredentialsPanel({
  state,
  onReload,
  onSaved,
  onNothingChanged,
  onSaveFailed,
}: CredentialsPanelProps) {
  const [values, setValues] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)

  const handleChange = (key: string, value: string) => {
    setValues((prev) => ({ ...prev, [key]: value }))
  }

  // 撤销对某个框的修改，回到预填值（掩码框失焦且为空时用）。
  const handleReset = (key: string) => {
    setValues((prev) => Object.fromEntries(Object.entries(prev).filter(([k]) => k !== key)))
  }

  if (state.kind === 'loading') {
    return (
      <section className={styles.section} aria-busy="true">
        <p className={styles.hint}>正在加载凭据配置…</p>
      </section>
    )
  }

  if (state.kind === 'error') {
    return (
      <section className={styles.section}>
        <p role="alert" className={styles.err}>
          凭据配置加载失败：{state.message}
          <button type="button" className={styles.retry} onClick={onReload}>
            重试
          </button>
        </p>
      </section>
    )
  }

  const credentials = state.data

  // 后端标明了哪些 key 的值是**占位串**（别人配的，不是自己的）。
  const maskedKeys = new Set(credentials.masked_key_fields)

  // **用户自己配过的** base_url。改 key 时用它做配对回填（见 handleSave）。
  //
  // ⚠️ **不能用「当前生效的 base_url」**——那可能是共享默认层/部署层的
  // 中转站。把用户的官方 key 绑到那个地址上就是密钥外泄。
  const currentUrls: Record<string, string> = {
    anthropic_base_url: credentials.user_anthropic_base_url ?? '',
    embedding_base_url: credentials.user_embedding_base_url ?? '',
  }

  const handleSave = async () => {
    const payload: CredentialsUpdate = {}
    // **三种状态要分清**（后端语义见 `app/gateway/credentials.py`）：
    //
    // | 前端发的 | 含义 |
    // |---|---|
    // | 有值 | 设成这个值 |
    // | `null` | **清空**这一项（回落到共享默认 / 部署默认） |
    // | 不发这个键 | 不改 |
    //
    // `values` 里**有键** = 用户碰过这个输入框（`handleChange` 只在
    // 用户输入时写它）。所以：
    //
    // - 有键且非空 → 发值
    // - 有键但空串 → 用户**主动清空** → 发 `null`
    // - 没键 → 没碰过 → 不发
    //
    // ⚠️ **主动清空必须发 `null`，不能发空串**：后端把空串当「没填」
    // 忽略，于是用户层里**旧的值原封不动保留**。典型后果：用户清空
    // 中转站地址、换上一把官方 key，保存后旧的中转站地址还在——那把
    // 官方 key 就被发到中转站，密钥外泄且界面无任何提示。
    for (const [key, value] of Object.entries(values)) {
      // **占位串（含 `•`）和清空的掩码框都不提交**。占位串被提交会加密存成
      // 用户的 key，之后每次调用 401 而界面显示「已配置」。
      // 但掩码框里**填了新 key 必须提交**——那是用户在覆盖默认 key。
      const trimmed = value.trim()
      if (maskedKeys.has(key) && (trimmed === '' || trimmed.includes('•'))) continue
      payload[key as keyof CredentialsUpdate] = trimmed.length > 0 ? trimmed : null
    }

    // **改了 key 就把它配对的 base_url 一起提交。**
    //
    // 后端要求 key 与 base_url 成对（见 services/credentials.py 的
    // `_pair`）：用户层只存 key 而不存 url 时，那把 key 会走官方端点
    // ——中转站的 key 走到官方端点必然认证失败。
    //
    // 而 url 输入框里**本来就填着当前生效的值**（用户看得见）。所以
    // 用户改 key 时，把那个 url 一起提交，两者在用户层成对落库。
    //
    // **不提交会怎样**：库里变成「有 key 没 url」→ key 走官方端点 →
    // 调用报认证失败，而用户界面上看不出哪里不对。
    //
    // ⚠️ **只用用户自己填过的 url**，不回退 `currentUrls`（那可能是
    // 共享默认层/部署层的中转站——把用户的官方 key 发到那里就是密钥
    // 外泄）。用户没碰过 url 时**不提交**它：用户层没有 url 时，
    // `_pair` 会让整层走用户层（key 走官方端点），这正是「用户只想
    // 用官方 key」的场景。
    for (const [key, urlKey] of Object.entries(PAIRED_URL_FIELD)) {
      // 没提交这把 key → 不用配对；用户碰过这个 url 框 → 用它的值
      //（可能是空串＝清空，已在上面处理）
      if (!(key in payload) || urlKey in values) continue
      // 用户没碰过 → 若用户层本来就有 url，保持它（不提交＝不改）
      const currentValue = currentUrls[urlKey] ?? ''
      if (currentValue.trim().length > 0) {
        payload[urlKey as keyof CredentialsUpdate] = currentValue.trim()
      }
    }

    if (Object.keys(payload).length === 0) {
      onNothingChanged()
      return
    }

    setSaving(true)
    try {
      await saveCredentials(payload)
      setValues({})
      onSaved()
      // 保存后重新拉取，刷新「值来自哪一层」与上面的供应商徽章。
      onReload()
    } catch (err) {
      onSaveFailed(err instanceof Error ? err.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const anthropicFields: FieldSpec[] = [
    {
      key: 'anthropic_api_key',
      label: 'API Key',
      masked: maskedKeys.has('anthropic_api_key'),
      placeholder: 'sk-ant-…',
      type: 'password',
      prefill: credentials.anthropic_api_key_value ?? '',
      hint: '留空则不修改。',
    },
    {
      key: 'anthropic_base_url',
      label: '中转站地址',
      placeholder: 'https://llmapi.pro',
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
      masked: maskedKeys.has('tavily_api_key'),
      placeholder: 'tvly-…',
      type: 'password',
      prefill: credentials.tavily_api_key_value ?? '',
      hint: '留空则不修改。',
    },
  ]

  const embeddingFields: FieldSpec[] = [
    {
      key: 'embedding_api_key',
      label: 'API Key',
      masked: maskedKeys.has('embedding_api_key'),
      placeholder: 'sk-…',
      type: 'password',
      prefill: credentials.embedding_api_key_value ?? '',
      hint: '留空则不修改。',
    },
    {
      key: 'embedding_base_url',
      label: '兼容端点',
      placeholder: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
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
        这些配置只对你自己生效，优先级高于共享默认值。密钥加密保存在本机数据库中。
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
        onChange={handleChange}
        onReset={handleReset}
      />
      <FieldGroup
        title="联网搜索（Tavily）"
        fields={tavilyFields}
        values={values}
        onChange={handleChange}
        onReset={handleReset}
      />
      <FieldGroup
        title="向量嵌入（Embedding）"
        fields={embeddingFields}
        values={values}
        onChange={handleChange}
        onReset={handleReset}
      />

      <div className={styles.actions}>
        <Button type="button" onClick={handleSave} disabled={saving}>
          {saving ? '保存中…' : '保存配置'}
        </Button>
      </div>
    </section>
  )
}

interface FieldGroupProps {
  title: string
  fields: FieldSpec[]
  values: Record<string, string>
  onChange: (key: string, value: string) => void
  onReset: (key: string) => void
}

/** 一组凭据字段。 */
function FieldGroup({ title, fields, values, onChange, onReset }: FieldGroupProps) {
  return (
    <fieldset className={styles.group}>
      <legend className={`${styles.groupTitle} font-label-sm text-secondary`}>{title}</legend>
      <div className={styles.fields}>
        {fields.map((field) => (
          <Field
            key={field.key}
            spec={field}
            value={values[field.key] ?? field.prefill ?? ''}
            onChange={onChange}
            onReset={onReset}
          />
        ))}
      </div>
    </fieldset>
  )
}

interface FieldProps {
  spec: FieldSpec
  value: string
  onChange: (key: string, value: string) => void
  onReset: (key: string) => void
}

/** 单个字段。 */
function Field({ spec, value, onChange, onReset }: FieldProps) {
  const inputId = `credential-${spec.key}`
  const hintId = `${inputId}-hint`
  // 密钥框默认打码，眼睛图标切「明文 / 掩码」。
  // 只有密钥类字段才有这个按钮——模型名与端点本来就是明文。
  const isSecret = spec.type === 'password'
  const [revealed, setRevealed] = useState(false)
  return (
    <div className={styles.field}>
      <Label htmlFor={inputId} className={styles.label}>
        {spec.label}
      </Label>
      <div className={styles.inputWrap}>
        <Input
          id={inputId}
          type={isSecret && !revealed ? 'password' : 'text'}
          value={value}
          placeholder={spec.placeholder}
          aria-describedby={hintId}
          // 占位串（别人配的 key）获得焦点即清空、失焦仍为空则恢复——
          // 不给在占位串上局部修改的机会。提交侧的兜底见 handleSave。
          onFocus={() => {
            if (spec.masked && value === spec.prefill) onChange(spec.key, '')
          }}
          onBlur={() => {
            if (spec.masked && value.trim() === '') onReset(spec.key)
          }}
          onChange={(e) => onChange(spec.key, e.target.value)}
          className={isSecret ? styles.secretInput : undefined}
        />
        {isSecret && (
          <button
            type="button"
            className={styles.reveal}
            onClick={() => setRevealed((prev) => !prev)}
            aria-label={revealed ? '隐藏内容' : '显示内容'}
            aria-pressed={revealed}
          >
            <IconSpan name={revealed ? 'visibility_off' : 'visibility'} size={18} />
          </button>
        )}
      </div>
      <p id={hintId} className={`${styles.hint} font-label-sm text-secondary`}>
        {spec.masked ? '当前用的是共享默认的密钥。点击输入框填入自己的 key 即可覆盖。' : spec.hint}
      </p>
    </div>
  )
}
