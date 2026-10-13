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
 * 列出某份资料的全部切片。
 *
 * 后端没有「按 chunk_id 取单片」的端点，所以这里拿全量再在前端筛。
 * 一份资料的切片数与它的大小成正比（长 PDF 能到上千片），全部拉回来
 * 只为取一片确实浪费——但角标是用户**主动点**才触发的，一次性交互，
 * 且 payload 已经在内网同源 cookie 后面。先不为此加后端端点；真要优化
 * 再补 `GET /sources/{id}/chunks/{chunk_id}`，那需要动后端路由。
 */
export async function fetchChunks(
  sourceId: number,
  signal?: AbortSignal,
): Promise<Chunk[]> {
  return apiFetch<Chunk[]>(`/api/v1/sources/${sourceId}/chunks`, { signal })
}

