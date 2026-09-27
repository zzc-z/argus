/**
 * Dashboard static mock data (Phase W1 — pre-backend).
 * Shape locked: KpiCard / RecentActivity / Subscriptions / ExploreGrid all consume this.
 *
 * Future real-API mapping (W2+):
 *   - KPIS          → GET /api/dashboard/kpis
 *   - ACTIVITIES    → GET /api/dashboard/activities
 *   - SUBSCRIPTIONS → GET /api/dashboard/subscriptions
 *   - REPORTS       → GET /api/dashboard/reports/continue
 */

export type FooterIconTone = 'success' | 'primary' | 'secondary'
export type ActivityBadgeTone = 'highlight' | 'muted' | 'plain' | 'warning'
export type ActivityIconBox = 'primary' | 'default' | 'accent'
export type SubscriptionBadgeTone = 'unread' | 'none' | 'paused'

export interface Kpi {
  id: string
  label: string
  icon: string
  value: string
  sub: string
  footerIcon: string
  footerIconTone: FooterIconTone
  footerPrefix: string
  footerHighlight: string
  footerSuffix: string
  /** 0-100; renders the bottom progress-bar width. */
  progress: number
}

export interface ActivityItem {
  id: string
  icon: string
  iconBox: ActivityIconBox
  title: string
  meta: string
  badgeText: string
  badgeTone: ActivityBadgeTone
  timestamp: string
  /** Newest row: violet highlight + 1px inset border. */
  highlight?: boolean
}

export interface Subscription {
  id: string
  title: string
  badgeText: string
  badgeTone: SubscriptionBadgeTone
  updatedAt: string
  source: string
  active: boolean
  paused?: boolean
}

export interface ExploreReport {
  id: string
  title: string
  tags: [string, string]
  activity: string
  agents: number
  citations: number
  footer: string
  ctaLabel: string
  ctaPrimary: boolean
  /** Material-symbol name used as a decorative cover hint (no external image). */
  coverIcon: string
  /** Background-image URL for the card cover (design argus_dashboard/code.html). */
  coverImage: string
}

export const KPIS: Kpi[] = [
  {
    id: 'topics',
    label: '活跃主题订阅',
    icon: 'rss_feed',
    value: '5',
    sub: '/ 8 最大配额',
    footerIcon: 'bolt',
    footerIconTone: 'secondary',
    footerPrefix: '过去 24 小时更新 ',
    footerHighlight: '3',
    footerSuffix: ' 个',
    progress: 62.5,
  },
  {
    id: 'sources',
    label: '已索引数据源',
    icon: 'database',
    value: '247',
    sub: '项已向量化',
    footerIcon: 'arrow_upward',
    footerIconTone: 'success',
    footerPrefix: '本周新增 ',
    footerHighlight: '+12',
    footerSuffix: ' 个 (12.4 GB)',
    progress: 78,
  },
  {
    id: 'reports',
    label: '本月生成研报',
    icon: 'auto_stories',
    value: '18',
    sub: '篇完整合成',
    footerIcon: 'verified',
    footerIconTone: 'primary',
    footerPrefix: '',
    footerHighlight: '12',
    footerSuffix: ' 篇包含完整学术基准溯源',
    progress: 45,
  },
  {
    id: 'memory',
    label: '长短期记忆项',
    icon: 'psychology',
    value: '89',
    sub: '活跃节点',
    footerIcon: 'insights',
    footerIconTone: 'secondary',
    footerPrefix: '包含 ',
    footerHighlight: '12',
    footerSuffix: ' 项核心偏好与反思逻辑',
    progress: 91,
  },
]

export const ACTIVITIES: ActivityItem[] = [
  {
    id: 'a1',
    icon: 'article',
    iconBox: 'primary',
    title: '深度研报《Q3 AI 融资与算力基准走势》已生成并完成交叉验证',
    meta: '节点 #DAG-8891 · 3 轮一致性对抗评估',
    badgeText: '已完成',
    badgeTone: 'highlight',
    timestamp: '2 小时前',
    highlight: true,
  },
  {
    id: 'a2',
    icon: 'neurology',
    iconBox: 'default',
    title: '抓取并向量化 14 篇权威学术与技术白皮书',
    meta: '注入知识库: Arxiv (cs.DC) · 维度 1536',
    badgeText: '已索引',
    badgeTone: 'muted',
    timestamp: '4 小时前',
  },
  {
    id: 'a3',
    icon: 'sync',
    iconBox: 'accent',
    title: '主题订阅“NVIDIA Earnings”捕获 12 条重要高管表态',
    meta: '包含 8 份分析师速记与 SEC Form 10-Q',
    badgeText: '已更新',
    badgeTone: 'muted',
    timestamp: '6 小时前',
  },
  {
    id: 'a4',
    icon: 'hub',
    iconBox: 'accent',
    title: '自适应反思器触发：校准量化指标提取格式模板',
    meta: '策略: JSON Schema v4 Strict Mode',
    badgeText: '已优化',
    badgeTone: 'plain',
    timestamp: '昨天 18:40',
  },
  {
    id: 'a5',
    icon: 'data_check',
    iconBox: 'default',
    title: '合规审计基线测试：检测到开源许可变更预警 (Apache 2.0 -> BSL)',
    meta: '源库：vLLM & TensorRT-LLM 依赖项',
    badgeText: '提示',
    badgeTone: 'warning',
    timestamp: '昨天 14:23',
  },
  {
    id: 'a6',
    icon: 'terminal',
    iconBox: 'default',
    title: '执行自动化回测任务：算力成本敏感度测算矩阵 (4x8 参数组)',
    meta: '耗时 142s · 消耗 148,200 tokens',
    badgeText: '已完成',
    badgeTone: 'muted',
    timestamp: '2 天前',
  },
  {
    id: 'a7',
    icon: 'archive',
    iconBox: 'default',
    title: '主题订阅“具身机器人”自动归档上月 86 条低权重新闻源',
    meta: '自动垃圾清理规则已执行',
    badgeText: '已整理',
    badgeTone: 'muted',
    timestamp: '3 天前',
  },
  {
    id: 'a8',
    icon: 'bookmark_added',
    iconBox: 'default',
    title: '新增知识库锚点：Stanford AI Index 2026 年度统计图表',
    meta: '图表解析模型: Vision Multimodal OCR',
    badgeText: '已完成',
    badgeTone: 'muted',
    timestamp: '3 天前',
  },
]

export const SUBSCRIPTIONS: Subscription[] = [
  {
    id: 's1',
    title: 'NVIDIA 财报与算力演进',
    badgeText: '12 条新动态',
    badgeTone: 'unread',
    updatedAt: '更新于 15 分钟前',
    source: '抓取源: SEC, Earnings Call',
    active: true,
  },
  {
    id: 's2',
    title: 'OpenAI 产品与架构动态',
    badgeText: '5 条新动态',
    badgeTone: 'unread',
    updatedAt: '更新于 2 小时前',
    source: '抓取源: DevDay, Research',
    active: true,
  },
  {
    id: 's3',
    title: '欧盟 AI 法案监管落地',
    badgeText: '2 条新动态',
    badgeTone: 'none',
    updatedAt: '更新于 昨天 09:30',
    source: '抓取源: EU Commission',
    active: true,
  },
  {
    id: 's4',
    title: '量子计算前沿突破',
    badgeText: '无未读',
    badgeTone: 'none',
    updatedAt: '更新于 2 天前',
    source: '抓取源: Nature, ArXiv Q-Bio',
    active: true,
  },
  {
    id: 's5',
    title: '具身机器人行业情报',
    badgeText: '已暂停监控',
    badgeTone: 'paused',
    updatedAt: '更新于 3 天前',
    source: '抓取源: Patent RSS, IEEE',
    active: false,
    paused: true,
  },
]

export const REPORTS: ExploreReport[] = [
  {
    id: 'r1',
    title: 'NVIDIA H100 与 Blackwell 大模型推理架构对比：吞吐量与 TCO 深度分析',
    tags: ['AI Hardware', '架构演进'],
    activity: '2 小时前活跃',
    agents: 5,
    citations: 23,
    footer: '进度: 100% 合成完毕',
    ctaLabel: '继续阅读 / 恢复会话',
    ctaPrimary: true,
    coverIcon: 'memory',
    coverImage:
      'https://lh3.googleusercontent.com/aida-public/AB6AXuAHiRfr3LD5xJtB2tEiex7rZd74c6JtZEGqYkjQ9AmRL3Uz9NNELcQxY2mVYGhujhqz96f61mlwvfjeNMc-EHkBVzGFdSm6-UAX4x4wUwbL4Wnw2N3hDlbHzKV98alpB5nDZWHHkXOR-Lw7gJn2wmyMItzmrNl3mVQPtmWX2f5y0L2GqzcZHJloCUgaXN3poCCph2v3PxocYzsJUbElL_mSdAzhWDIFgrhVwzxO7Neie9vS6YM19RTT',
  },
  {
    id: 'r2',
    title: 'Q3 全球 AI 大模型基础设施投融资与训练集群利用率基准研报',
    tags: ['资本趋势', '算力集群'],
    activity: '昨天生成',
    agents: 4,
    citations: 18,
    footer: '已完成交叉校验',
    ctaLabel: '查看研报',
    ctaPrimary: false,
    coverIcon: 'analytics',
    coverImage:
      'https://lh3.googleusercontent.com/aida-public/AB6AXuAU4mO4XmBoIXUSudKYeAZZCqGDyYNOKikXZ3SmKpRQ2WeGAHGBx_BENb5hPhgwjd6qjujcxKENTgamN1eBgFql4rBgQLAAEY9fxPt_DfOUj9wr5s0VhRmNtCT7GiqEagwoz8ikZp6PufbOzfW5JCntOSBO4V4P1d6j83oWyCHnBzqd5yO2utasjyi--uGAxEbt5OpOnsR4OWW6_Ae4KH9dAomhQ3Ve6Vv8IvYpI5afXvjRMzjOf1wg',
  },
  {
    id: 'r3',
    title: '欧盟 AI 法案合规执行路线图：开源模型与企业部署基线',
    tags: ['政策监管', '企业合规'],
    activity: '3 天前生成',
    agents: 6,
    citations: 31,
    footer: '风险模型审计完备',
    ctaLabel: '查看研报',
    ctaPrimary: false,
    coverIcon: 'gavel',
    coverImage:
      'https://lh3.googleusercontent.com/aida-public/AB6AXuAKYtkBAoAZ2JL_wllmsMwv8qYdbzfxP2tSMz4ftKJb5lCoJQQap9fUitx9FVKE2bj_PDS06iPJHdJPXbuGWojV9CMfl__MBmGScJ1bIz2PrDSCyGMIkgncc9YdV744X9zSxb6-J-XW2j5jeQT_4PI1K-Usy4Ks0vqywJk-0wjCULifzo7CIVsiYm0wfjsrIYWCEV0Fn6mY_qZjkyh26gRGjiFo4HkUMWWvu98xdIZY7I5BStLlzGpK',
  },
]
