/**
 * Static mock data for the /notifications route.
 *
 * Shape mirrors a real backend payload (sections grouped by recency,
 * each section holding typed notifications) so swapping in a fetch is a
 * one-line change later. All copy is 1:1 with argus_notifications/code.html.
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

export const todaySection: NotificationSection = {
  title: '今天 / Today',
  count: '3 条动态',
  tail: 'DAG_SYNC: REALTIME',
  live: true,
  items: [
    {
      id: 'n1',
      tag: '【主题动态】',
      title: 'NVIDIA 财报与算力架构演进 捕获 12 条新情报',
      time: '20 分钟前',
      timeDetail: '10:42',
      body: '覆盖 Q3 FY26 电话会议完整速记、SEC Form 10-Q 披露及 Blackwell GB200 机架供货预期更新。',
      icon: 'radar',
      severity: 'info',
      unread: true,
      category: 'subscriptions',
      chips: {
        topic: '硬件与芯片',
        source: '源: SEC Edgar & SemiAnalysis',
        sentiment: '+14.2% 情绪指数',
      },
      sparkline: 'M1 12L12 8L24 14L36 4L48 9L63 2',
    },
    {
      id: 'n2',
      tag: '【研报就绪】',
      title: '《NVIDIA H100 与 Blackwell 大模型推理架构对比》已完成多智能体交叉校验',
      time: '2 小时前',
      timeDetail: '08:30',
      body: '由 5 个智能体协同构建,引用 23 篇官方白皮书与学术基准,综合置信度 98.2%。已同步推送到“芯片与大模型算力”知识库。',
      icon: 'assignment_turned_in',
      severity: 'success',
      unread: true,
      category: 'reports',
      confidence: {
        score: '置信度评分 98.2%',
        summary: '5 个智能体验证节点通过',
      },
      badge: '深度研报',
    },
    {
      id: 'n3',
      tag: '【记忆更新】',
      title: '自适应推理引擎已学习 3 条研究员新偏好',
      time: '4 小时前',
      timeDetail: '06:15',
      body: '已记录:优先提取 FP4/FP8 吞吐比矩阵、自动补充液冷 PUE 评估模型规则、过滤非同行评议的预印本引文。',
      icon: 'psychology',
      severity: 'memory',
      unread: true,
      category: 'memory',
      memoryWeight: '记忆权重: 0.94 (高优先级)',
    },
  ],
}

export const yesterdaySection: NotificationSection = {
  title: '昨天 / Yesterday',
  count: '3 条历史',
  tail: 'ARCHIVED',
  items: [
    {
      id: 'n4',
      tag: '【每周周报】',
      title: '《欧盟 AI 法案 (EU AI Act) 合规落地指引》周度合规汇总已生成',
      time: '昨天 14:23',
      body: '重点监控开源通用模型 (GPAI) 透明度准则演进与高风险系统自评流程。',
      icon: 'feed',
      severity: 'info',
      unread: false,
      category: 'weekly',
      tailTag: '已归档至合规专题',
    },
    {
      id: 'n5',
      tag: '【系统提示】',
      title: '信源订阅已自动暂停:"TechCrunch AI 原文流"',
      time: '昨天 11:05',
      body: '因目标网站触发 Cloudflare WAF 验证阻断,重试 3 次失败,建议更换 RSS 订阅地址或添加自定义代理 Header。',
      icon: 'warning',
      severity: 'warning',
      unread: false,
      category: 'system',
      errorCode: 'ERROR_CODE: HTTP_403_WAF',
    },
    {
      id: 'n6',
      tag: '【向量化入库】',
      title: 'TSMC 2nm 制程节点备忘录已完成双层切片并入库',
      time: '昨天 09:12',
      body: '新增 44 Chunks,关联 1 篇进行中的芯片制程专题报告,嵌入模型:text-embedding-3-large。',
      icon: 'dataset',
      severity: 'info',
      unread: false,
      category: 'ingestion',
    },
  ],
}

export const earlierSection: NotificationSection = {
  title: '更早之前 / Earlier this week',
  count: '36 条记录',
  items: [
    {
      id: 'n7',
      tag: '【信源同步】',
      title: 'arXiv 计算机视觉 6 篇新论文已被抓取摘要',
      time: '3 天前',
      body: '',
      icon: 'rss_feed',
      severity: 'info',
      unread: false,
      category: 'rss',
    },
    {
      id: 'n8',
      tag: '【权限变更】',
      title: '研究助理 Lisa 申请访问“大语言模型算力基准”知识库',
      time: '4 天前',
      body: '',
      icon: 'key',
      severity: 'info',
      unread: false,
      category: 'permission',
    },
  ],
}

export const allSections: NotificationSection[] = [todaySection, yesterdaySection, earlierSection]

export const totalCount = 42
export const unreadCount = 3

export const typeOptions = [
  { value: 'all', label: '全部类型 (All)' },
  { value: 'subscriptions', label: '主题订阅 (Subscriptions)' },
  { value: 'reports', label: '研报交付 (Reports)' },
  { value: 'system', label: '系统事件 (System)' },
] as const

export type TypeFilterValue = (typeof typeOptions)[number]['value']

export const viewModes = [
  { value: 'time', label: '按时间倒序', icon: 'schedule' },
  { value: 'source', label: '按信源聚合', icon: 'hub' },
] as const

export type ViewMode = (typeof viewModes)[number]['value']
