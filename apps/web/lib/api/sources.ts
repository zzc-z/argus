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
 * 的切片数与文件大小成正比（CHUNK_SIZE=512 字符，50MB 上限能到几万片），
 * 单次响应十几 MB。同一份报告里点 3 个角标 = 3 次全量往返，且每次都要在
 * 主线程 `res.json()` 解析一遍。缓存把这个降到 1 次。
 *
 * ## 失效
 *
 * 没有主动失效机制——资料被重传后 chunk_id 会变，但缓存里存的是旧 id，
 * `find` 会返回 undefined，落到「该切片已不存在」的错误分支（这是对的：
 * 报告里的引用确实已经失效）。真要拿到新内容，重新提问即可，新一轮会走
 * 新的 source 流程。刻意不做 TTL：报告是一次性会话产物，为它引入定时器
 * 换来的新鲜度收益接近零。
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

