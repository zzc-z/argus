'use client'

import * as React from 'react'
import { EmptyState } from '@/components/common/EmptyState'
import { useRouter } from 'next/navigation'

import { PageLayout } from '@/components/common/PageLayout'
import { SourceFilterBar } from './components/SourceFilterBar'
import { SourceFilterSidebar } from './components/SourceFilterSidebar'
import { SourceBulkRibbon } from './components/SourceBulkRibbon'
import { SourceTable } from './components/SourceTable'
import { SourcePagination } from './components/SourcePagination'
import { ApiError } from '@/lib/api/client'
import { deleteSource, fetchSources, type SourceV as ApiSource } from '@/lib/api/sources'
import {
  countByStatus,
  countByType,
  filterSources,
  toSourceRows,
  type RowStatus,
} from './lib/sourceTypes'
import styles from './page.module.css'

export default function SourcesPage() {
  const router = useRouter()
  // 存的是**后端对象**而非表格行：筛选与统计都要原始 status / source_type，
  // 映射后的展示态（status 已压成 3 态、kind 已翻成英文标签）反推不回去。
  const [sources, setSources] = React.useState<ApiSource[]>([])
  const [loading, setLoading] = React.useState(true)
  const [errorText, setErrorText] = React.useState<string | null>(null)
  // **字符串**：PlainTable 的 getRowId/selectedIds 契约是 string。
  // 真要发请求时 Number() 转回——后端 id 是 int。
  const [selectedIds, setSelectedIds] = React.useState<Set<string>>(new Set())
  // 筛选状态。空集合 = 不过滤该维度。
  const [selectedTypes, setSelectedTypes] = React.useState<ReadonlySet<ApiSource['source_type']>>(
    new Set(),
  )
  const [selectedStatuses, setSelectedStatuses] = React.useState<ReadonlySet<RowStatus>>(new Set())

  const refresh = React.useCallback(async (signal: AbortSignal) => {
    try {
      const data = await fetchSources(signal)
      setSources(data.items)
      setErrorText(null)
    } catch (err) {
      if (signal.aborted) return
      // 401 不在这里报：登录态由布局层的 UserMenu 负责（未登录时它给的是
      // 「去登录」入口）。列表页再弹一条「未登录」横幅，等于把同一件事说
      // 两遍，且它会盖在筛选栏上方、看起来像筛选坏了。
      if (err instanceof ApiError && err.status === 401) {
        setErrorText(null)
        return
      }
      setErrorText(err instanceof Error ? err.message : '加载资料失败')
    } finally {
      if (!signal.aborted) setLoading(false)
    }
  }, [])

  React.useEffect(() => {
    const controller = new AbortController()
    // react-hooks/set-state-in-effect 的误报：setRows 发生在**异步网络请求的
    // 回调里**（await 之后），不是 effect body 里的同步调用。与
    // `lib/auth/UserContext.tsx` 同一处理——本项目不引数据层，effect 是唯一选择。
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh(controller.signal)
    return () => controller.abort()
  }, [refresh])

  const rows = React.useMemo(
    () => toSourceRows(filterSources(sources, selectedTypes, selectedStatuses)),
    [sources, selectedTypes, selectedStatuses],
  )

  const typeCounts = React.useMemo(() => countByType(sources), [sources])
  const statusCounts = React.useMemo(() => countByStatus(sources), [sources])

  const toggleIn =
    <T,>(set: React.Dispatch<React.SetStateAction<ReadonlySet<T>>>) =>
    (v: T) =>
      set((prev) => {
        const next = new Set(prev)
        if (next.has(v)) next.delete(v)
        else next.add(v)
        return next
      })

  const toggleType = toggleIn(setSelectedTypes)
  const toggleStatus = toggleIn(setSelectedStatuses)

  const toggleRow = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleAll = () => {
    setSelectedIds((prev) => {
      if (prev.size === rows.length) return new Set()
      return new Set(rows.map((r) => String(r.id)))
    })
  }

  const allChecked = rows.length > 0 && selectedIds.size === rows.length
  const indeterminate = selectedIds.size > 0 && selectedIds.size < rows.length

  const indexedCount = rows.filter((r) => r.status === 'ready' || r.status === 'processing').length
  const failedCount = rows.filter((r) => r.status === 'failed').length

  const onBulkDelete = React.useCallback(async () => {
    const ids = [...selectedIds]
    if (ids.length === 0) return
    // 删资料不可撤销（连带删掉它的全部切片与向量），必须先确认。
    // 用 window.confirm：与 settings 页既有的破坏性操作同一套交互。
    const ok = window.confirm(
      `确认删除选中的 ${ids.length} 份资料？\n\n删除后其全部切片与向量都会一并移除，且无法恢复。`,
    )
    if (!ok) return

    setErrorText(null)
    // 逐条串行而不是 Promise.all：并发删时任意一条失败会让整个 all reject，
    // 已成功的那些却无从得知，用户只看到「什么都没删」。串行能精确报出
    // 「删了几份、失败几份」。
    let failed = 0
    for (const id of ids) {
      try {
        await deleteSource(Number(id))
      } catch {
        failed += 1
      }
    }
    setErrorText(failed === 0 ? null : `${failed} 份删除失败，其余已删除`)
    setSelectedIds(new Set())
    await refresh(new AbortController().signal)
  }, [selectedIds, refresh])

  return (
    <PageLayout
      header={{
        title: '资料库 (Source Library)',
        enLabel: 'RAG Vector Hub',
        stats: [
          { label: '个数据源', value: rows.length },
          { label: '已索引', value: indexedCount },
          // 失败数不是装饰：摄取失败是常态（抓取超时、格式不支持），不给
          // 数字的话用户得逐行找红色 badge。
          { label: '失败', value: failedCount, tone: failedCount > 0 ? 'highlight' : 'default' },
        ],
        actions: [
          { label: '+ 上传新资料', icon: 'add_circle', variant: 'primary', href: '/add-sources' },
        ],
      }}
    >
      <SourceFilterBar
        counts={typeCounts}
        total={sources.length}
        active={selectedTypes}
        onChange={setSelectedTypes}
      />
      <div className={styles.workspace}>
        <SourceFilterSidebar
          typeCounts={typeCounts}
          statusCounts={statusCounts}
          selectedTypes={selectedTypes}
          selectedStatuses={selectedStatuses}
          onToggleType={toggleType}
          onToggleStatus={toggleStatus}
        />
        <div className={styles.stage}>
          {errorText && <p role="alert">{errorText}</p>}
          <SourceBulkRibbon
            selectedCount={selectedIds.size}
            allChecked={allChecked}
            indeterminate={indeterminate}
            onToggleAll={toggleAll}
            onBulkDelete={onBulkDelete}
          />
          <SourceTable
            data={rows}
            selection={{
              selectedIds,
              onToggle: toggleRow,
              onToggleAll: toggleAll,
              allSelected: allChecked,
              partiallySelected: indeterminate,
            }}
          />
          {loading ? (
            <p className={styles.loading}>加载中…</p>
          ) : rows.length === 0 ? (
            /* 「库里本来就没有」和「筛选后没有」必须分开说：后者给不出
               「上传资料」的建议——用户已经有资料了，他需要的是清筛选。 */
            sources.length === 0 ? (
              <EmptyState
                icon="upload_file"
                title="资料库还是空的"
                description="上传 PDF、网页或文本资料后，系统会自动切片、向量化并建好索引，之后的提问就能引用到这些资料。"
                action={{ label: '+ 上传新资料', onClick: () => router.push('/add-sources') }}
              />
            ) : (
              <EmptyState
                icon="filter_alt_off"
                title="没有符合筛选条件的资料"
                description={`当前筛选命中 0 条，共 ${sources.length} 条资料。放宽类型或状态条件即可看到更多。`}
                action={{
                  label: '清空筛选条件',
                  onClick: () => {
                    setSelectedTypes(new Set())
                    setSelectedStatuses(new Set())
                  },
                }}
              />
            )
          ) : (
            <SourcePagination total={sources.length} shown={rows.length} />
          )}
        </div>
      </div>
    </PageLayout>
  )
}
