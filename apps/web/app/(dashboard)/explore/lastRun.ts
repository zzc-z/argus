/**
 * 「上次研究」的本地记录。
 *
 * ## 为什么需要它
 *
 * explore 页的运行态（正文、DAG 推进、工具轨迹）全在组件的 `useState` 里，
 * 切页 = 组件卸载 = 状态蒸发。**报告本身是落盘的**（后端 `reports` 表），
 * 所以内容找得回来，只是 explore 页自己不知道有。
 *
 * 这个模块记下「最近一次跑出来的报告 id + 问题原文」，切页回来时
 * explore 就能给出入口：「上次的研究已保存，去看看」。
 *
 * ## 为什么存 localStorage 而不是让后端查
 *
 * 后端已经有 `GET /api/v1/reports` 能列出报告，探索页完全可以调它取最近
 * 一条。为什么不这么做？
 *
 * - 后端返回的是**所有**报告，不区分「上次那一条是不是本设备跑的」。
 *   一个人多设备登录时，explore 会显示另一台设备上的报告——不是「上次」。
 * - 多一次网络往返，而 localStorage 是同步的，切页回来立刻能显示。
 *
 * 代价：换浏览器/清缓存就没了。但那本来也不是「上次」的可靠定义。
 *
 * ## 存什么
 *
 * 只存**展示需要的最小字段**。正文不存——它有十几 KB，localStorage 不该
 * 装这种东西，而且真要读正文该去 `/report/{id}`。
 */

/** localStorage 键。前缀 `argus:` 与项目其它 localStorage 用法一致。 */
const STORAGE_KEY = 'argus:explore:last-run'

/**
 * 同页内的变更通知事件名。
 *
 * `storage` 事件**只跨标签页传播**——同一页里写 localStorage 不会通知
 * 任何监听者。所以同页内要自己派发这个事件。
 */
export const LAST_RUN_EVENT = 'argus:explore:last-run-changed'

/** 一次已保存的研究。 */
export interface LastRun {
  /** 报告 id，对应 `/report/{id}`。 */
  reportId: number
  /** 提问原文。用于显示「上次问的是……」与一键重新提问。 */
  question: string
  /** 一次研究的会话 id。与后端 `reports.session_id` 同源。 */
  sessionId: string
  /** 落盘时间，ISO 串。用于显示「X 分钟前」。 */
  savedAt: string
}

/**
 * 读上次的研究。
 *
 * 读不出来就返回 null——localStorage 可能被禁用（隐私模式）、被清空、
 * 或里面的值是旧版本写的畸形 JSON。**每种情况都只是「没有上次」**，
 * 不该让整页崩掉。
 */
export function readLastRun(): LastRun | null {
  return parseLastRun(getLastRunSnapshot())
}

/**
 * 把快照字符串解析成 `LastRun`。
 *
 * 单独抽出来是因为 `useSyncExternalStore` 的 getSnapshot 必须返回**稳定**
 * 的值（原始字符串），而组件要的是对象。解析放在这里做，组件用
 * `useMemo` 按快照字符串缓存，避免每次渲染都 new 一个对象。
 */
export function parseLastRun(raw: string | null): LastRun | null {
  if (!raw) return null
  try {
    const parsed: unknown = JSON.parse(raw)
    if (!isLastRun(parsed)) return null
    return parsed
  } catch {
    // 畸形 JSON——当成没有。
    return null
  }
}

/** 记下这次研究。写失败（配额满、隐私模式）不该影响研究本身。 */
export function writeLastRun(run: LastRun): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(run))
  } catch {
    // 忽略：存不上只是少了恢复入口，不该让研究失败。
    return
  }
  notifyChanged()
}

/** 清掉记录。用户主动开始新一轮研究时用不到——但「重新提问」后应该更新。 */
export function clearLastRun(): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.removeItem(STORAGE_KEY)
  } catch {
    // 同上。
    return
  }
  notifyChanged()
}

/** 通知同页的订阅者：记录变了。 */
function notifyChanged(): void {
  window.dispatchEvent(new Event(LAST_RUN_EVENT))
}

/**
 * 订阅记录变化。返回退订函数。
 *
 * 跨标签页的 `storage` 事件也一并听——另一个标签页跑完研究，这边也该
 * 看到恢复入口。
 */
export function subscribeLastRun(onChange: () => void): () => void {
  if (typeof window === 'undefined') return () => {}
  window.addEventListener(LAST_RUN_EVENT, onChange)
  window.addEventListener('storage', onChange)
  return () => {
    window.removeEventListener(LAST_RUN_EVENT, onChange)
    window.removeEventListener('storage', onChange)
  }
}

/**
 * 读记录的**原始字符串**快照。
 *
 * `useSyncExternalStore` 要求 getSnapshot 返回一个**稳定**的值——每次调用
 * 都返回新对象会让 React 认为快照一直在变，陷入无限重渲染。所以这里
 * 返回 localStorage 里的原始字符串（同一个字符串就是同一个值），
 * 由 `parseLastRun` 把它变成对象。
 */
export function getLastRunSnapshot(): string | null {
  if (typeof window === 'undefined') return null
  try {
    return window.localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

/**
 * 校验解析出来的值是不是合法的 `LastRun`。
 *
 * localStorage 里的东西**不可信**——用户可以随便改，别的脚本也可能写。
 * 类型断言（`as LastRun`）不做任何检查，改一个字段名就会让下游拿到
 * `undefined` 再拼进 URL。所以这里逐字段查。
 */
function isLastRun(value: unknown): value is LastRun {
  if (typeof value !== 'object' || value === null) return false
  const v = value as Record<string, unknown>
  return (
    typeof v.reportId === 'number' &&
    Number.isInteger(v.reportId) &&
    v.reportId > 0 &&
    typeof v.question === 'string' &&
    typeof v.sessionId === 'string' &&
    typeof v.savedAt === 'string'
  )
}
