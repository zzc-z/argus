/**
 * 「最近一轮」的本地记录 —— **只是回退线索，不是权威**。
 *
 * ## 它现在是什么
 *
 * run id 的**权威在 URL**（`/explore?run=xxx`）。URL 能分享、能收藏、
 * 多标签页各跑各的 —— 那是主流项目的做法。
 *
 * 这个模块只在一种情况下有用：用户从别的页面直接点进 `/explore`，
 * 地址栏里**没有** run id。那一轮就接不回来了，他看到一片空白，以为自己
 * 刚才白问了。
 *
 * 所以这里记一份「我最近一轮是什么」，让前端在无 id 时能问一次后端、
 * 把 URL 补上。
 *
 * ## 为什么不能只靠它
 *
 * localStorage 是全局一份 —— 两个标签页会互相覆盖：一个标签页的提问被
 * 另一个抢走。URL 每个标签页各有一份，天然隔离。
 *
 * ## 与 `lastRun.ts` 的分工
 *
 * | | `lastRun.ts` | 本模块 |
 * |---|---|---|
 * | 记什么 | **已完成**的那一轮（报告 id） | **最近**的一轮的 run id |
 * | 用途 | 「上次的研究已保存」入口 | 无 id 时找回当前这一轮 |
 * | 存哪 | localStorage | localStorage（URL 是权威，这里是线索） |
 */

/** localStorage 键。前缀 `argus:` 与项目其它 localStorage 用法一致。 */
const STORAGE_KEY = 'argus:explore:active-run'

/**
 * 读最近一轮的 run id。
 *
 * 读不出来就返回 null —— localStorage 可能被禁用（隐私模式）、被清空、
 * 或里面的值是旧版本写的畸形值。**每种情况都只是「不知道」**，不该让
 * 整页崩掉。
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

/** 记下最近一轮的 run id。写失败不该影响研究本身。 */
export function writeActiveRunId(runId: string): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(STORAGE_KEY, runId)
  } catch {
    // 存不上只是「无 id 时找不回来」，不该让研究失败。
    return
  }
}

/** 清掉记录。 */
export function clearActiveRunId(): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.removeItem(STORAGE_KEY)
  } catch {
    return
  }
}
