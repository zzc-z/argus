'use client'

import * as React from 'react'
import { PageLayout } from '@/components/common/PageLayout'
import { ApiError } from '@/lib/api/client'
import {
  createSourceFromUrl,
  fetchSources,
  fetchSource,
  uploadSource,
  type SourceV,
} from '@/lib/api/sources'
import { QueueMonitor } from './components/QueueMonitor'
import { UploadDropZone } from './components/UploadDropZone'
import { UrlRssTabs } from './components/UrlRssTabs'
import { toQueueRow } from './lib/queueTypes'
import styles from './page.module.css'

/** 轮询间隔。后端摄取分 6 个阶段，每阶段提交一次；1.5s 足够跟上也够省。 */
const POLL_MS = 1500

export default function AddSourcesPage() {
  // 原始 `SourceV` 而非展示行：轮询要按 id 逐个更新，映射留到渲染时做。
  const [sources, setSources] = React.useState<SourceV[]>([])
  const [busy, setBusy] = React.useState(false)
  // 上传错误归 dropzone 自己报，URL 错误归表单自己报——所以这里只留一个
  // state 给**上传**用。URL 错误由 UrlRssTabs 内部渲染（它离输入框更近，
  // 用户不用眼睛来回扫）。
  const [uploadErrors, setUploadErrors] = React.useState<string[]>([])
  /** 初次加载失败。空字符串表示没出错。 */
  const [loadError, setLoadError] = React.useState<string | null>(null)
  const [urlError, setUrlError] = React.useState<string | null>(null)

  // 后端两种建源入口的参数完全不同（文件上传走 multipart；URL 走 JSON + title 必填）。

  // 挂载时先拉一次全量。**队列不能只装本次会话上传的**：用户在
  // 另一个标签页上传、或摄取途中刷新页面，库里那些「正在切片」的资料
  // 就再也不会出现在这里——用户会以为上传丢了。
  React.useEffect(() => {
    const controller = new AbortController()
    void fetchSources(controller.signal)
      .then((list) => {
        setLoadError(null)
        setSources(
          // **不按状态过滤**。这里显示的是「我这批资料的摄取记录」，
          // 已完成的也要留着——只显示未完成的等于用户传完、刷新一下，
          // 列表就空了，看起来像没传成功。
          // 只有「正在处理」的才需要轮询，那件事由下面的定时器负责。
          [...list.items].sort((a, b) => (a.created_at < b.created_at ? 1 : -1)),
        )
      })
      .catch((err: unknown) => {
        // **只吞 401**——那是「没登录」，由布局层的 AuthGuard 处理（它会
        // 把页面换成登录入口，这里报不报都一样）。
        //
        // 其余错误（500、网络挂、后端发版重启）**必须报**：原来这里
        // `.catch(() => undefined)` 吞掉一切，后端一挂队列就静默变空，
        // 用户看到的正是「我刚传的文件不见了」——因为他确实传过。
        if (err instanceof ApiError && err.status === 401) return
        setLoadError(err instanceof ApiError ? err.message : '加载资料列表失败')
      })
    return () => controller.abort()
  }, [])

  const queue = React.useMemo(() => sources.map(toQueueRow), [sources])

  // 轮询：每份未完成的资料一条独立的自调度链。
  //
  // ## 为什么不��「固定间隔 + 遍历所有 pending id」
  //
  // 那种写法（setInterval 每 1.5s 对每个 pending id 各发一个请求）有两个
  // 叠加的问题：
  //
  // 1. **请求会堆叠**。后端正满负荷解析 20 份 PDF 时，单次 fetchSource
  //    可能要好几秒——但定时器不管上一个请求回没回来，照发不误。稳态下
  //    20 份资料能同时挂着 40+ 个在途请求，每个都要开 DB session 查库。
  //    UI 上看不出异常，只是后端 QPS 悄悄涨一个量级。
  // 2. **定时器永不停**。setInterval 一旦建成就跑到组件卸载，与 pending
  //    列表无关——全部 indexed/failed 之后它还在空转。
  //
  // 改成自调度链后：请求**完成后**才安排下一拍，慢请求自动把节奏拉慢，
  // 不可能堆叠；pending 集合空了链就自然终止。
  //
  // ## 为什么每个 id 一条链，而不是一条链轮询所有 id
  //
  // 一条链串行轮询所有 id 时，第 N 个 id 的状态要等前 N-1 个跑完才更新
  // ——10 份资料时最后一个要等 15 秒。每条链独立，最坏延迟是 1 个 RTT。
  //
  // ## ref 存「正在轮询的 id 集合」
  //
  // 用 ref 而不是把 id 列表放进依赖：列表每次渲染都是新数组，写进 deps
  // 会让 effect 每拍重建（等于没节流）；写成 `pendingIds.join(',')` 能过
  // lint 但闭包捕获的是**首次**那份列表——上传第二份资料后它就再也不会
  // 被轮询到。
  const pollingRef = React.useRef(new Map<number, () => void>())

  /**
   * 启动一条轮询链。返回停止函数。
   *
   * 自调度：请求 → 等 POLL_MS → 再请求。**不在途就不发下一次**，
   * 这是与固定间隔写法的本质区别。
   */
  function startPolling(sourceId: number): () => void {
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | null = null
    const controller = new AbortController()

    const tick = async () => {
      if (stopped) return
      try {
        const fresh = await fetchSource(sourceId, controller.signal)
        if (stopped) return
        setSources((prev) => prev.map((s) => (s.id === fresh.id ? fresh : s)))
        // 已经完成就别再排下一拍了——链自然终止
        if (fresh.status === 'indexed' || fresh.status === 'failed') {
          pollingRef.current.delete(sourceId)
          return
        }
      } catch {
        /* 单次轮询失败不打断整体——下一拍再试。真失败会在
           后端把 status 置成 failed 并带 error_message。 */
        if (stopped) return
      }
      timer = setTimeout(() => void tick(), POLL_MS)
    }

    timer = setTimeout(() => void tick(), POLL_MS)

    return () => {
      stopped = true
      controller.abort()
      if (timer !== null) clearTimeout(timer)
    }
  }

  // 在 **effect 里**同步（不是渲染期写 ref——那在并发渲染下会拿到
  // 未提交的队列），定时器读 ref 拿到的永远是最近一次提交后的值。
  React.useEffect(() => {
    const pending = new Set(queue.filter((q) => !q.done && !q.failed).map((q) => q.id))

    // 停掉已经不需要轮询的（已 indexed / failed，或被删了）
    for (const [id, stop] of pollingRef.current) {
      if (!pending.has(id)) {
        stop()
        pollingRef.current.delete(id)
      }
    }
    // 为新出现的启动轮询
    for (const id of pending) {
      if (!pollingRef.current.has(id)) {
        pollingRef.current.set(id, startPolling(id))
      }
    }
  }, [queue])

  // 组件卸载时停掉所有链——否则 setState 打在已卸载组件上。
  React.useEffect(() => {
    const chains = pollingRef.current
    return () => {
      for (const stop of chains.values()) stop()
      chains.clear()
    }
  }, [])

  const handleFiles = React.useCallback(async (files: File[]) => {
    if (files.length === 0) return
    setBusy(true)
    setUploadErrors([])
    for (const file of files) {
      try {
        const created = await uploadSource(file)
        setSources((prev) => [created, ...prev])
      } catch (err) {
        // 逐条上报而不是第一批失败就停：用户传 5 个文件，前 2 个
        // 不支持不代表后 3 个也不行。
        //
        // **累积而不是覆盖**：`setUploadError` 每次都冲掉上一条，用户
        // 传 5 个文件、3 个失败时只看得见最后一个的错，前两个无声无息。
        // 现在每条失败都留在一份列表里，全部列出来。
        setUploadErrors((prev) => [
          ...prev,
          // `ApiError.message` 已经带上后端的 `detail`（client.ts 里合并过），
          // ApiError 上没有独立的 detail 字段。
          err instanceof ApiError ? `${file.name}：${err.message}` : `${file.name}：上传失败`,
        ])
      }
    }
    setBusy(false)
  }, [])

  const handleUrl = React.useCallback(async (input: { url: string; title: string }) => {
    setBusy(true)
    setUrlError(null)
    try {
      const created = await createSourceFromUrl({
        url: input.url,
        title: input.title,
        source_type: 'html',
      })
      setSources((prev) => [created, ...prev])
    } catch (err) {
      // 同步失败（422 title/url 不合法、401）只能在这里报——请求根本没建源，
      // 队列里没有对应行。抓取失败是异步的，落在队列的 error_message 上。
      setUrlError(err instanceof ApiError ? err.message : 'URL 建源失败')
    } finally {
      setBusy(false)
    }
  }, [])

  return (
    <PageLayout
      header={{
        title: '添加资料源',
        subtitle: '摄取后的资料会在提问时被检索',
      }}
    >
      <div className={styles.grid}>
        <section className={styles.left}>
          <UploadDropZone onFilesSelected={handleFiles} />
          <UrlRssTabs onSubmit={handleUrl} submitting={busy} error={urlError} />
          {uploadErrors.length > 0 && (
            <div className={styles.error} role="alert">
              {uploadErrors.map((message) => (
                <p key={message} className={styles.errorLine}>
                  {message}
                </p>
              ))}
            </div>
          )}
        </section>
        <div className={styles.right}>
          {loadError && (
            <p className={styles.error} role="alert">
              加载资料列表失败：{loadError}
            </p>
          )}
          <QueueMonitor items={queue} />
        </div>
      </div>
    </PageLayout>
  )
}
