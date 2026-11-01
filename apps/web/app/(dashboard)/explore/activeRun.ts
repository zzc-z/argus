/**
 * 「当前这一轮」的本地记录。
 *
 * ## 要解决什么
 *
 * explore 页的生成态在服务端（后端的 run 注册表），但**服务端不知道
 * 浏览器里开着哪个 run**——用户可能开了两个标签页各跑一个。所以前端
 * 要自己记下 run id，刷新之后才知道该接回哪一轮。
 *
 * 与 `lastRun.ts` 是两件事，别混：
 *
 * | | `lastRun.ts` | 本模块 |
 * |---|---|---|
 * | 记什么 | **已完成**的那一轮（报告 id） | **正在进行/刚完成**的那一轮（run id） |
 * | 用途 | 给「上次的研究已保存」入口 | 刷新/切页后**接回流** |
 * | 什么时候清 | 用户开始新一轮时 | 新的 run 起来时（旧的被覆盖） |
 *
 * ## 为什么存 localStorage 而不是只存内存
 *
 * 内存（`useState`）在刷新后就没了——而刷新正是要解决的场景。
 * localStorage 在同一标签页刷新后仍在。
 *
 * 跨标签页共享是**故意的**：两个标签页会互相覆盖对方的 run id。
 * 那会不会错接？两个标签页接的是同一个后端 run（run id 一样），
 * 只是各自渲染一份——内容一致，不会错。真正的问题是「一个标签页的
 * 提问被另一个标签页抢走」，那种场景下 run id 被覆盖后新标签页会
 * 接回**旧**那一轮，看起来像「我的新问题没跑」。这是已知取舍：
 * 要彻底解决得把 run id 放进 URL（主流项目的做法），留到下一轮。
 */

/** localStorage 键。前缀 `argus:` 与项目其它 localStorage 用法一致。 */
const STORAGE_KEY = 'argus:explore:active-run'

/** 同页内的变更通知事件名。 */
export const ACTIVE_RUN_EVENT = 'argus:explore:active-run-changed'

/**
 * 读当前 run id。
 *
 * 读不出来就返回 null——localStorage 可能被禁用（隐私模式）、被清空、
 * 或里面的值是旧版本写的畸形值。**每种情况都只是「没有当前 run」**，
 * 不该让整页崩掉。
 */
export function readActiveRunId(): string | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    return raw && raw.length > 0 ? raw : null
  } catch {
    return null
  }
}

/** 记下当前 run id。写失败不该影响研究本身。 */
export function writeActiveRunId(runId: string): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(STORAGE_KEY, runId)
  } catch {
    // 存不上只是「刷新后接不回来」，不该让研究失败。
    return
  }
  notifyChanged()
}

/** 清掉记录。用户主动开始新一轮时用不到——但新一轮的 run id 会覆盖它。 */
export function clearActiveRunId(): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.removeItem(STORAGE_KEY)
  } catch {
    return
  }
  notifyChanged()
}

/** 通知同页的订阅者：记录变了。 */
function notifyChanged(): void {
  window.dispatchEvent(new Event(ACTIVE_RUN_EVENT))
}

/**
 * 订阅记录变化。返回退订函数。
 *
 * 跨标签页的 `storage` 事件也一并听——另一个标签页跑完研究，这边也该
 * 知道 run id 变了。
 */
export function subscribeActiveRun(onChange: () => void): () => void {
  if (typeof window === 'undefined') return () => {}
  window.addEventListener(ACTIVE_RUN_EVENT, onChange)
  window.addEventListener('storage', onChange)
  return () => {
    window.removeEventListener(ACTIVE_RUN_EVENT, onChange)
    window.removeEventListener('storage', onChange)
  }
}
