/**
 * /notifications 的**类型定义与筛选选项常量**。
 *
 * 历史上这里还有 8 条历史通知（`todaySection` / `allSections`）与整套侧栏假数据
 * （`pushSettings` / `healthSnapshot`），全部删除：后端没有 notifications 表，
 * 也没有任何通知查询接口，那些条目与指标是编的。
 *
 * **类型不能删、也不能挪到别处**：`lib/notifications/NotificationsContext.tsx`
 * 从这里 import `NotificationCategory` / `NotificationSeverity` /
 * `NotificationWithMeta`。文件路径保持不变，导入方无需改动。
 *
 * 页面现在只显示 `NotificationsContext` 里由其他页面推送的真实增量事件
 * （localStorage 键 `argus:notifications-extra`）。
 */

export type NotificationCategory =
  'subscriptions' | 'reports' | 'memory' | 'weekly' | 'system' | 'ingestion' | 'rss' | 'permission'

export type NotificationSeverity = 'info' | 'success' | 'warning' | 'memory'

export interface NotificationBase {
  id: string
  /** Brief category prefix used as a leading tag, e.g. "【主题动态】". */
  tag: string
  title: string
  /** Short relative timestamp shown to the right of the title. */
  time: string
  /** Optional fine-grained timestamp, e.g. "10:42". */
  timeDetail?: string
  body: string
  /** Material Symbols icon ligature shown inside the left badge square. */
  icon: string
  severity: NotificationSeverity
  /** True for unread items (purple-tinted background). */
  unread: boolean
  category: NotificationCategory
}

export interface NotificationWithMeta extends NotificationBase {
  /** Topic / source chip + sentiment percentage (Subscriptions type). */
  chips?: { topic: string; source: string; sentiment: string }
  /** Inline SVG path for the sparkline (Subscriptions type). */
  sparkline?: string
  /** Confidence + agent-validation row (Reports type). */
  confidence?: { score: string; summary: string }
  /** "深度研报" / "已归档至..." tag shown next to confidence. */
  badge?: string
  /** Trailing link tag, e.g. "已归档至合规专题". */
  tailTag?: string
  /** For warning items, machine-readable error code. */
  errorCode?: string
  /** Memory weight shown on Memory items. */
  memoryWeight?: string
}

export interface NotificationSection {
  /** Section heading shown above the items, e.g. "今天 / Today". */
  title: string
  /** Small status pill next to the title, e.g. "3 条动态". */
  count: string
  /** Right-aligned tail label, e.g. "DAG_SYNC: REALTIME". */
  tail?: string
  /** Decorative dot rendered before the title when true (today section). */
  live?: boolean
  items: NotificationWithMeta[]
}

/** 类型筛选项。取值是 `NotificationCategory` 的子集 + `all`。 */
export const typeOptions = [
  { value: 'all', label: '全部类型 (All)' },
  { value: 'subscriptions', label: '主题订阅 (Subscriptions)' },
  { value: 'reports', label: '研报交付 (Reports)' },
  { value: 'system', label: '系统事件 (System)' },
  { value: 'memory', label: '记忆演化 (Memory)' },
  { value: 'weekly', label: '每周周报 (Weekly)' },
  { value: 'ingestion', label: '向量化入库 (Ingestion)' },
] as const

export type TypeFilterValue = (typeof typeOptions)[number]['value']
