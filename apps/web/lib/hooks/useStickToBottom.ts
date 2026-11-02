'use client'

import * as React from 'react'

/**
 * 流式内容的「贴底滚动」。
 *
 * ## 要解决什么
 *
 * 报告正文是流式追加的：内容越长，滚动容器越需要往下走，否则用户盯着
 * 的是半截旧内容，新字在视口外看不见——「文字出现了但没跟着走」。
 *
 * ## 主流项目怎么做（ChatGPT / Claude / Perplexity 都是这个交互）
 *
 * 1. 内容增长时**自动滚到底**
 * 2. 用户**手动往上滚**时**停止跟随**——不能抢用户的滚动条
 * 3. 用户滚回底部时**恢复跟随**
 * 4. 暂停期间给一个「回到底部」的浮标
 *
 * 第 2 条是关键。只做第 1 条的话，用户想回头看前面一段，结果正文还在
 * 增长，页面一直把他往下拽——想看的东西被强行推走。
 *
 * ## 阈值为什么是 100px
 *
 * 「到底部」不能判成严格等于 0：亚像素滚动、padding-bottom、浏览器
 * 的弹性滚动都会让差值停在几像素上。100px 的容差既够松（不会因为
 * 1px 的误差就判定「用户离开了底部」），又够紧（用户真的往上翻了
 * 100px 以上就该停）。
 */

/** 距底部多少像素内算「还在底部」。 */
const BOTTOM_THRESHOLD_PX = 100

/**
 * 让滚动容器在内容增长时跟随底部。
 *
 * ## 为什么 ref 由调用方传进来
 *
 * 早先这个 hook 自己建 ref 再返回 `{ ref, paused, scrollToBottom }`。
 * 那样返回的对象里**嵌着一个 ref**，ESLint 的 `react-hooks/refs` 规则
 * 会把整个返回值当成「可能是个 ref」，于是在渲染期读它的任何属性
 * （`stick.ref`、`stick.paused`）都被判成「渲染期访问 ref」而报错。
 *
 * 改成「调用方建 ref、传进来」之后，hook 返回的只有普通值与函数，
 * 规则无从误判 —— 而且这本来就是 React 里更常见的写法：ref 归组件所有。
 *
 * @param ref 滚动容器的 ref。**由调用方建**（`useRef`）。
 * @param content 依赖它变化的「内容长度」——用它触发跟随。它必须是**单调
 *   递增**的（流式文本的长度正合适）。用对象或数组当依赖会每次渲染都变，
 *   导致跟随逻辑被反复触发。
 * @returns 跟随状态与操作。**不含 ref**（见上）。
 */
export function useStickToBottom(
  ref: React.RefObject<HTMLElement | null>,
  content: number,
): { paused: boolean; scrollToBottom: (behavior?: ScrollBehavior) => void } {
  const [paused, setPaused] = React.useState(false)
  // 用 ref 存「是否跟随」，避免每次 setState 都触发闭包重建。
  const followingRef = React.useRef(true)

  const scrollToBottom = React.useCallback(
    (behavior: ScrollBehavior = 'smooth') => {
      const el = ref.current
      if (!el) return
      followingRef.current = true
      setPaused(false)
      el.scrollTo({ top: el.scrollHeight, behavior })
    },
    [ref],
  )

  // 用户手动滚动 → 判断他是在往上看还是在回底部。
  //
  // **每次 scroll 事件都重新判断「是否在底部」**，不区分触发来源。
  // 原因：程序滚动永远停在底部，所以它触发的事件算出来的结果一定是
  // 「在底部」→ 不暂停。用户上滚算出来是「不在底部」→ 暂停。
  //
  // 试过用「程序滚动置标志、事件里消费」的写法，标志会残留——内容
  // 增长后 scrollTop 与记录值对不上，下一次**用户**滚动被误吞，
  // 表现为「跟随莫名其妙停了」。
  React.useEffect(() => {
    const el = ref.current
    if (!el) return

    const onScroll = () => {
      const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight
      const atBottom = distanceToBottom <= BOTTOM_THRESHOLD_PX
      followingRef.current = atBottom
      setPaused(!atBottom)
    }

    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [ref])

  // 内容增长 → 跟随到底。
  React.useEffect(() => {
    const el = ref.current
    if (!el || !followingRef.current) return
    // 无动画：流式内容每 100ms 增长一次，smooth 动画会互相打断，
    // 视觉上是「一顿一顿」而不是平滑跟随。主流项目在这里也用 instant。
    //
    // 赋 ``scrollTop = scrollHeight``。内容在我们赋值之后还会继续增长，
    // 此刻的 scrollHeight 不是最终底部——下一轮内容增长时会再校正一次，
    // 误差只有一片的高度。
    el.scrollTop = el.scrollHeight
  }, [ref, content])

  return { paused, scrollToBottom }
}
