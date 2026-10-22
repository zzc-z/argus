'use client'

import * as React from 'react'
import { useMemo } from 'react'

import { PageLayout } from '@/components/common/PageLayout'
import { EmptyState } from '@/components/common/EmptyState'
import { useNotifications } from '@/lib/notifications'
import { NotificationSection } from './components/NotificationSection'
import { HealthCard } from './components/HealthCard'

import styles from './page.module.css'

/**
 * /notifications — 通知中心。
 *
 * ## 真实数据只有一处
 *
 * 后端**没有通知系统**：数据库里只有 users / accounts / sources /
 * document_chunks / reports / report_sources 六张表，没有 notifications 表，
 * 也没有任何通知查询接口。所以本页不再展示任何"历史通知"列表——
 * 那 8 条按今天 / 昨天 / 更早分组的记录是编的，已删除。
 *
 * 现在唯一的真实来源是 `NotificationsContext`：**其他页面在运行时推送的
 * 增量事件**，持久化在浏览器 localStorage 的 `argus:notifications-extra` 下。
 * 有推送就列出来，没有就显示空态——空态说明白"为什么空"，而不是编一条假的。
 *
 * ## 删掉的无源区块
 *
 * - 筛选栏 / 批量工具栏 / 分页：作用在假数据集上（总数 42 条、3 页假分页），
 *   没有数据源，删除。
 * - 推送设置卡片：后端没有推送信道 / 短信开关的配置接口。
 * - CTA 卡片：指向"配置多智能体 DAG"，没有落点。
 * - 健康快照卡片：改成接真实的 `GET /api/v1/healthz`（见 HealthCard）。
 *
 * 布局（流列 + 右侧栏）与配色未动，删的是无数据源的区块。
 */
export default function NotificationsPage() {
  const { extras, markedReadIds, markRead, markAllRead, dismissNotification } = useNotifications()

  // 已读状态存在 store 里（markedReadIds），条目的 unread 字段是推送时的快照，
  // 两者合并才是当前真实状态。
  const items = useMemo(
    () => extras.map((it) => ({ ...it, unread: it.unread && !markedReadIds.has(it.id) })),
    [extras, markedReadIds],
  )

  const unreadCount = useMemo(() => items.filter((it) => it.unread).length, [items])

  return (
    // 本页自带面包屑头部，不走 PageLayout 的默认 PageHeader，
    // 所以不传 header（PageLayout 内部按 `header ?` 判断，传 null 也能跑，
    // 但类型声明是可选而非 nullable，传 null 过不了 tsc）。
    <PageLayout>
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-2 pt-[8px] pb-2">
        <div className="flex flex-col">
          <div className="flex items-center gap-1 text-secondary font-label-sm text-label-sm mb-1">
            <span>控制台</span>
            <span className="material-symbols-outlined text-[14px]">chevron_right</span>
            <span className="text-primary font-code">/notifications</span>
            <span
              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-surface-container-high text-on-surface-variant font-code text-[10px] ml-2"
              id="realtime-stream-pill"
            >
              <span className="w-1.5 h-1.5 rounded-full bg-primary" />
              来源：浏览器本地存储
            </span>
          </div>
          <div className="flex items-baseline gap-2">
            <h1 className="font-headline-lg text-headline-lg text-on-surface tracking-tight">
              通知中心 / Notifications
            </h1>
            <span className="font-label-md text-label-md text-secondary font-code">
              [{unreadCount} 条未读]
            </span>
          </div>
          <p className="font-body-sm text-body-sm text-secondary mt-1">
            只列出其他页面在本次浏览中推送到本地的事件，后端不保存通知历史
          </p>
        </div>
        <div className="flex items-center gap-1 self-start md:self-auto">
          <button
            type="button"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-surface-container-lowest hover:bg-surface-container text-on-surface transition-colors shadow-sm text-body-sm font-body-sm"
            id="markAllBtn"
            onClick={markAllRead}
          >
            <span className="material-symbols-outlined text-[16px] text-primary">done_all</span>
            <span>全部标为已读</span>
          </button>
        </div>
      </div>

      <div className={styles.grid}>
        <div className={styles.streamCol}>
          {items.length === 0 ? (
            <EmptyState
              icon="notifications_off"
              title="暂无通知事件"
              description="后端目前没有通知服务——数据库里没有 notifications 表，也没有 /api/v1/notifications 接口，所以这里不会展示任何历史通知。通知中心只显示由其他页面在运行时推送到本浏览器的事件（写入 localStorage 的 argus:notifications-extra）；目前没有事件被推送，列表为空。"
            />
          ) : (
            <NotificationSection
              section={{
                title: '推送事件 / Pushed Events',
                count: `${items.length} 条`,
                items,
              }}
              onMarkRead={markRead}
              onDismiss={dismissNotification}
            />
          )}
        </div>

        <aside className={styles.sideCol}>
          <HealthCard />
        </aside>
      </div>
    </PageLayout>
  )
}
