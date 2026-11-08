/**
 * 耗时格式化。
 *
 * 单独一个文件而不是放在 page.tsx 里：page.tsx 导入 AgentDAG，
 * AgentDAG 也要用它——放一起会形成循环依赖。
 */

/**
 * 把毫秒格式化成耗时文案。
 *
 * 小于 100 毫秒时显示「<0.1s」而不是「0.0s」——「0.0s」读起来像
 * 「没跑」，而实际是跑了但很快。
 */
export function formatElapsed(ms: number): string {
  const seconds = ms / 1000
  return seconds < 0.1 ? '<0.1s' : `${seconds.toFixed(1)}s`
}
