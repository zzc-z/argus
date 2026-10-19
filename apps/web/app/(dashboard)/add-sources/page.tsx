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
  const [uploadError, setUploadError] = React.useState<string | null>(null)
  const [urlError, setUrlError] = React.useState<string | null>(null)

  // 后端两种建源入口的参数完全不同（文件上传走 multipart；URL 走 JSON + title 必填）。

  // 挂载时先拉一次全量。**队列不能只装本次会话上传的**：用户在
  // 另一个标签页上传、或摄取途中刷新页面，库里那些「正在切片」的资料
  // 就再也不会出现在这里——用户会以为上传丢了。
  React.useEffect(() => {
    const controller = new AbortController()
    void fetchSources(controller.signal)
      .then((list) =>
        setSources(
          // **不按状态过滤**。这里显示的是「我这批资料的摄取记录」，
          // 已完成的也要留着——只显示未完成的等于用户传完、刷新一下，
          // 列表就空了，看起来像没传成功。
          // 只有「正在处理」的才需要轮询，那件事由下面的定时器负责。
          [...list.items].sort((a, b) => (a.created_at < b.created_at ? 1 : -1)),
        ),
      )
      // 401 不报：登录态由布局层的 UserMenu 负责。
      .catch(() => undefined)
    return () => controller.abort()
  }, [])

  const queue = React.useMemo(() => sources.map(toQueueRow), [sources])

  // 未完成的那几个要轮询。全部 indexed/failed 后 effect 自然停。
  //
  // 用 ref 而不是把 id 列表放进依赖：列表每次渲染都是新数组，写进 deps
  // 会让定时器每拍重建（等于没节流）；写成 `pendingIds.join(',')` 能过
  // lint 但闭包捕获的是**首次**那份列表——上传第二份资料后它就再也不会
  // 被轮询到。ref 让定时器读到的永远是当前值，且 effect 只跑一次。
  const pendingRef = React.useRef<number[]>([])

  // 在 **effect 里**同步（不是渲染期写 ref——那在并发渲染下会拿到
  // 未提交的队列），定时器读 ref 拿到的永远是最近一次提交后的值。
  React.useEffect(() => {
    pendingRef.current = queue.filter((q) => !q.done && !q.failed).map((q) => q.id)
  }, [queue])

  React.useEffect(() => {
    const timer = setInterval(() => {
      for (const id of pendingRef.current) {
        void fetchSource(id)
          .then((fresh) => setSources((prev) => prev.map((s) => (s.id === fresh.id ? fresh : s))))
          .catch(() => {
            /* 单次轮询失败不打断整体——下一拍再试。真失败会在
               后端把 status 置成 failed 并带 error_message。 */
          })
      }
    }, POLL_MS)
    return () => clearInterval(timer)
  }, [])

  const handleFiles = React.useCallback(async (files: File[]) => {
    if (files.length === 0) return
    setBusy(true)
    setUploadError(null)
    for (const file of files) {
      try {
        const created = await uploadSource(file)
        setSources((prev) => [created, ...prev])
      } catch (err) {
        // 逐条上报而不是第一批失败就停：用户传 5 个文件，前 2 个
        // 不支持不代表后 3 个也不行。
        setUploadError(
          // `ApiError.message` 已经带上后端的 `detail`（client.ts 里合并过），
          // ApiError 上没有独立的 detail 字段。
          err instanceof ApiError ? `${file.name}：${err.message}` : `${file.name}：上传失败`,
        )
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
          {uploadError && (
            <p className={styles.error} role="alert">
              {uploadError}
            </p>
          )}
        </section>
        <div className={styles.right}>
          <QueueMonitor items={queue} />
        </div>
      </div>
    </PageLayout>
  )
}
