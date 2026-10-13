/**
 * 资料 / 切片接口的前端镜像。
 *
 * 字段对齐后端 `apps/api/app/schemas/source.py` 的 `SourceResponse` 与
 * `ChunkResponse`——改了那边必须同步改这里。
 */

import { apiFetch } from './client'

/** 切片详情。与后端 `ChunkResponse` 一一对应。 */
export interface Chunk {
  id: number
  /** 该片在这份资料里的序号，0 起。 */
  chunk_index: number
  content: string
  /**
   * 页序（1 起）；null = 没有分页概念的资料（网页）。
   *
   * 纯文本**也可能有值**：parser 按 `\f`（换页符）切段并从 1 编号。
   * 所以它不是「PDF 专属字段」，而是「原文里第几段」。
   */
  page: number | null
  /** 切片在原始文本里的字符区间 [start, end)。 */
  start_offset: number
  end_offset: number
}

/**
 * 资料切片的进程内缓存。sourceId → 该资料的全量切片。
 *
 * ## 为什么需要它
 *
 * 后端没有「按 chunk_id 取单片」的端点，只能拉全量再在前端筛。一份资料
 * 的切片数与文件大小成正比（CHUNK_SIZE=512 字符），单次响应可达上百 MB。
 * 同一份报告里点 3 个角标 = 3 次全量往返，且每次都要在主线程 `res.json()`
 * 解析一遍。缓存把这个降到 1 次。
 *
 * ## 什么时候必须清
 *
 * **登出。** logout 走的是 `router.push` 客户端导航，不重载模块，
 * 模块级 Map 原样存活——上一个用户的私有资料全文会留在 JS 堆里，
 * 而下一次命中缓存连一次带鉴权的请求都不发，「资料已删除」也感知不到。
 * argus 的整个前提就是「私有资料」，所以登出时清是硬要求，不是优化。
 *
 * ## 什么时候可以不清
 *
 * 重新提问时清（见 `clearChunkCache` 的调用点）：资料被重传后 chunk_id 会
 * 变，但缓存里存的是旧 id，`find` 返回 undefined，落到「该切片已不存在」
 * 的错误分支——这是对的，报告里的引用确实已经失效。
 *
 * ## 内存上界
 *
 * **没有上界，这是已知的取舍。** 上限内的一个 50MB `.txt` 能切出十万多片，
 * parsed 后常驻百 MB 级；多份资料叠加更糟，移动端 Safari 上足以让标签页 OOM。
 * 根治要补 `GET /sources/{id}/chunks/{chunk_id}`（后端路由改动）。
 * 在那之前，至少该按累计字符数截断——但那会让缓存行为变得不可预测
 * （用户不知道自己的引用还准不准），所以先不做，等有真实 OOM 反馈再说。
 */
const chunkCache = new Map<number, Chunk[]>()

/**
 * 列出某份资料的全部切片（带缓存）。
 *
 * 先补全量再筛是后端缺单片端点下的次优解。真要根治要补
 * `GET /sources/{id}/chunks/{chunk_id}`，那需要动后端路由。
 */
export async function fetchChunks(
  sourceId: number,
  signal?: AbortSignal,
): Promise<Chunk[]> {
  const cached = chunkCache.get(sourceId)
  if (cached) return cached

  const chunks = await apiFetch<Chunk[]>(`/api/v1/sources/${sourceId}/chunks`, { signal })
  chunkCache.set(sourceId, chunks)
  return chunks
}

/** 提问开始时清缓存——上一轮的资料可能已被重摄取。 */
export function clearChunkCache(): void {
  chunkCache.clear()
}

