'use client'

/**
 * 引用忠实度校验结论面板（Critic 节点）。
 *
 * 刻意**不阻断**：后端已跑完多轮检索，把未支撑的角标从正文里剔除等于让
 * 它的工作白费。这里只把结论标注出来让用户自己判断。
 *
 * ## 为什么必须有「校验中」这一态
 *
 * 后端把 done 事件**先于**校验帧发出（`agent.py`：先 `yield ledger.done()`
 * 再 `_settle()`），因为 judge 调用最坏 120s × 3 次重试，挡在 done 前面
 * 会让用户在报告读完后干等，且会占死 `MAX_CONCURRENT_STREAMS` 的准入。
 *
 * 代价是这段窗口里 UI 上「一切正常」：DAG 五节点已 completed、收尾统计
 * 已出、报告打字机已结束，而校验面板还不存在。若此时不画任何东西，
 * **「面板没出现」和「校验全通过」在视觉上完全一样**——用户会认定
 * 引用没问题然后关掉页面。所以收到 done 就要立刻画「校验中」。
 *
 * ## 四种终态 + 一种中间态
 *
 *   - 校验中：done 已到、faithfulness 未到。
 *   - 中断：结论永远没来（流在 done 之后被掐断）。**不能回落成「不显示」**——
 *     「面板不存在」与「全部通过」在视觉上一样，用户会读成没问题。
 *   - skipped：压根没走到校验（无引用 / 无对应原文 / 调用失败 / 模型未判定）。
 *     画成「通过率 0%」会把「没检查」说成「全部无据」，方向完全相反。
 *   - checked > 0 且有 unsupported：真结论，逐条列出句子 + 理由。
 *   - checked > 0 且无 unsupported：全通过，一行结论即可，不占空间。
 *
 * `missing` 两种 skipped 分支都要显示：后端 `faithfulness.py` 的「引用表里
 * 没有对应原文」那条路径**必然带非空 missing**（只在 `verifiable` 为空而
 * `cited` 非空时触发，此时 `missing == cited`），而悬空的角标号恰恰是用户
 * 最需要知道的那个——把它吞掉等于面板只交代了一半结论。另两条 skipped
 * 路径（调用失败 / 模型未判定）的 missing 则可能为空，所以渲染时按长度判断。
 */

import type * as React from 'react'

import { IconSpan } from '@/components/common/IconSpan'
import type { FaithfulnessEventV, UnsupportedV } from '@/lib/api/sse'
import styles from './index.module.css'

export interface FaithfulnessPanelProps {
  report: FaithfulnessEventV
}

interface PanelShellProps {
  icon: string
  /** CSS Modules 的类名类型是 `string | undefined`，与取值方式保持一致。 */
  iconClass: string | undefined
  tag: string
  tagClass: string | undefined
  children: React.ReactNode
}

/**
 * 通过率的展示文本。
 *
 * 分母是 `checked`（**实际判定过的条数**），不是角标总数——模型没回的条目
 * 已被后端从分母里剔除（`faithfulness.py` 的 `unjudged`）。除零防护在调用
 * 它的 `FaithfulnessPanel` 里（`skipped || checked === 0` 先 early return），
 * 这里不必重复判：两个 boolean 的组合一旦以后放宽，这处会静默印出 `"NaN%"`。
 */
function formatRate(report: FaithfulnessEventV): string {
  return `${((report.supported / report.checked) * 100).toFixed(0)}%`
}

/** `missing` 是**标注层面**的问题（正文引用了引用表里没有的编号），与忠实度无关——单独一句。 */
function MissingHint({ numbers }: { numbers: number[] }) {
  if (numbers.length === 0) return null
  return (
    <p className={styles.missing}>
      正文中有 {numbers.map((n) => `[${n}]`).join('、')} 未出现在引用表中。
    </p>
  )
}

/**
 * 面板外壳。
 *
 * 五种形态共用的只是「一个带标题行的 section」，正文各不相同——所以只把
 * 壳提出来，内容仍由各处自给。
 *
 * `role="status"`：面板是在 done 帧之后**新挂载**的，读屏用户不会因为焦点
 * 没落在这里就自动得知「结论开始了」——这个组件的整个立论就是让用户知道
 * 结论到没到，对读屏用户这条链不能断。
 */
function PanelShell({ icon, iconClass, tag, tagClass, children }: PanelShellProps) {
  return (
    <section className={styles.panel} aria-label="引用校验" role="status">
      <div className={styles.head}>
        <IconSpan name={icon} size={14} className={iconClass} />
        <span>引用校验</span>
        <span className={tagClass}>{tag}</span>
      </div>
      {children}
    </section>
  )
}

/** 校验进行中。done 已到但结论未到的那段窗口。 */
export function FaithfulnessPending() {
  return (
    <PanelShell
      icon="fact_check"
      iconClass={styles.headIconMuted}
      tag="校验中"
      tagClass={styles.tagMuted}
    >
      <p className={styles.reason}>正在核对引用是否能在原文中找到支撑，结果稍后给出。</p>
    </PanelShell>
  )
}

/**
 * 结论永远没到。
 *
 * 与「不渲染任何东西」必须区分：面板空白 = 用户读到「引用没问题」，
 * 而这里真实发生的是「校验压根没跑完」。这是本组件存在的全部理由——
 * 让每一个「没有结论」的时刻都被显式说出来。
 *
 * 调用方负责在本轮压根失败（红色横幅已说明原因）时不渲染它：那种情况下
 * 没有报告、没有引用，「重试可得到结论」指向一个不存在的问题。
 */
export function FaithfulnessAbort() {
  return (
    <PanelShell
      icon="fact_check"
      iconClass={styles.headIconMuted}
      tag="未完成"
      tagClass={styles.tagMuted}
    >
      <p className={styles.reason}>
        校验未完成，引用是否被原文支撑尚未核对。重试本次提问可得到结论。
      </p>
    </PanelShell>
  )
}

/** 一条未被支撑的引用。单独成组件是为了把 JSX 嵌套压回 4 层上限内。 */
function UnsupportedItem({ item }: { item: UnsupportedV }) {
  return (
    <li className={styles.item}>
      <span className={styles.footnote}>[{item.footnote}]</span>
      <div className={styles.itemBody}>
        <p className={styles.sentence}>{item.sentence}</p>
        {item.reason && <p className={styles.itemReason}>{item.reason}</p>}
      </div>
    </li>
  )
}

export function FaithfulnessPanel({ report }: FaithfulnessPanelProps) {
  // `checked === 0` 与 `skipped` 是两个独立的判据，不能只看后者。
  // 后端保证 skipped 时 checked 必为 0，但**反过来不保证**：数据跨网络
  // 边界，前端不该把「没判定过任何一条」画成绿色对勾——那是把「没检查」
  // 说成「全部通过」。reason 可能是空的，那也不能显示成空白。
  if (report.skipped || report.checked === 0) {
    return (
      <PanelShell
        icon="fact_check"
        iconClass={styles.headIconMuted}
        tag="未校验"
        tagClass={styles.tagMuted}
      >
        <p className={styles.reason}>{report.reason || '本次运行没有可校验的引用'}</p>
        <MissingHint numbers={report.missing} />
      </PanelShell>
    )
  }

  const hasIssues = report.unsupported.length > 0

  return (
    <PanelShell
      icon={hasIssues ? 'error_outline' : 'verified'}
      iconClass={hasIssues ? styles.headIconWarn : styles.headIconOk}
      tag={formatRate(report)}
      tagClass={hasIssues ? styles.tagWarn : styles.tagOk}
    >
      {/* 分母是「实际判定过的条数」，不是报告里的角标总数。这里显式写出
          两个数字，避免用户把「20 条角标校验了 18 条」误读成漏了 2 条。 */}
      <p className={styles.reason}>
        已判定 {report.checked} 条引用，其中 {report.supported} 条能在原文中找到支撑
        {report.unsupported.length > 0 && `，${report.unsupported.length} 条未能找到`}。
      </p>

      <MissingHint numbers={report.missing} />

      {hasIssues && (
        // role="list"：Safari / VoiceOver 在 `list-style: none` 时会**有意**移除
        // 列表语义（读屏不再播报「N 项列表」）——这不算 bug，是 WebKit 对
        // 「视觉上去掉项目符号的列表」的既定处理，且是否触发还取决于嵌套上下文。
        // role="list" 是标准补法，CSS 补不了这个语义。
        <ul className={styles.list} role="list">
          {/* key 用 footnote 即可：后端 `verifiable` 由 `sorted(set(cited))` 过滤而来，
              无重复，每个编号最多产出一条 Unsupported。 */}
          {report.unsupported.map((u) => (
            <UnsupportedItem key={u.footnote} item={u} />
          ))}
        </ul>
      )}
    </PanelShell>
  )
}
