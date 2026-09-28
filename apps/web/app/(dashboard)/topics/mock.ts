/**
 * Mock data for the Topics (主题订阅管理) page.
 * 1:1 with the table rows in argus_topics/code.html. Static for now — when the
 * backend lands, swap this for an API call inside a server component.
 */

export type Frequency = 'realtime' | '6h' | 'daily' | 'weekly'

export interface SourceChip {
  /** Material Symbols icon name (must exist in Outlined catalog). */
  icon: string
  /** Tailwind colour token for the leading icon (uses 47-token palette). */
  iconTone?: 'primary' | 'secondary'
  label: string
  /** Tooltip string shown on the chip. Mirrors the `title` attr in HTML. */
  hint?: string
}

export interface Topic {
  id: string
  title: string
  /** 课题分类 (e.g. "硬件&算力"). */
  category: string
  description: string
  /** Agent identifier printed under the description. */
  agent: string
  /** Whether `深度置信过滤开启` is on for this row. */
  deepFilter: boolean
  sources: SourceChip[]
  /** 最近更新时间 — pre-formatted in source (e.g. "15 分钟前"). */
  updatedAt: string
  /** Sub-text under updatedAt (e.g. "10:42:19 巡检"). */
  updatedDetail: string
  unreadLabel: string
  /** Tone of the unread chip — controls background colour. */
  unreadTone: 'primary' | 'secondary' | 'muted'
  frequency: Frequency
  /** Whether the subscription is currently active. */
  active: boolean
}

export interface FrequencyOption {
  value: Frequency
  label: string
}

export const FREQUENCY_OPTIONS: FrequencyOption[] = [
  { value: 'realtime', label: '实时 (Real-time)' },
  { value: '6h', label: '每 6 小时' },
  { value: 'daily', label: '每天 (Daily)' },
  { value: 'weekly', label: '每周 (Weekly)' },
]

export interface TopicFilterTab {
  id: 'all' | 'running' | 'paused' | 'archived'
  label: string
  /** Static counts per the design's segmented tabs. */
  count: number
}

export const FILTER_TABS: TopicFilterTab[] = [
  { id: 'all', label: '全部订阅', count: 7 },
  { id: 'running', label: '持续监控中', count: 5 },
  { id: 'paused', label: '已暂停', count: 2 },
  { id: 'archived', label: '历史归档', count: 0 },
]

export const TOPICS: Topic[] = [
  {
    id: 'nvidia',
    title: 'NVIDIA 财报与算力架构演进',
    category: '硬件&算力',
    description: '覆盖 GTC 发布会、SEC Form 10-Q/K 申报、NVLink 拓扑及 Blackwell 产线交付追踪',
    agent: 'SemiAnalyst-DAG',
    deepFilter: true,
    sources: [
      {
        icon: 'feed',
        iconTone: 'primary',
        label: 'RSS 3 个',
        hint: 'SEC EDGAR, Financial Times, Bloomberg',
      },
      {
        icon: 'language',
        iconTone: 'secondary',
        label: '公开 Web 12 个',
        hint: "Semiconductor Bull, TrendForce, Tom's Hardware",
      },
      {
        icon: 'database',
        iconTone: 'secondary',
        label: '财报数据库 1 个',
        hint: 'CapitalIQ SEC Engine',
      },
    ],
    updatedAt: '15 分钟前',
    updatedDetail: '10:42:19 巡检',
    unreadLabel: '12 条未读',
    unreadTone: 'primary',
    frequency: 'realtime',
    active: true,
  },
  {
    id: 'openai',
    title: 'OpenAI 产品策略与前沿架构动态',
    category: '基础模型',
    description: '抓取 DevDay 动向、System 2 推理强化学习论文、GPT 系列模型更新及高管公开发言',
    agent: 'RL-Reasoner-Trace',
    deepFilter: false,
    sources: [
      { icon: 'menu_book', label: 'Arxiv cs.AI' },
      { icon: 'forum', label: 'Twitter/X List' },
      { icon: 'article', label: '官方技术博客' },
    ],
    updatedAt: '2 小时前',
    updatedDetail: '08:50:04 巡检',
    unreadLabel: '5 条未读',
    unreadTone: 'secondary',
    frequency: '6h',
    active: true,
  },
  {
    id: 'eu-ai-act',
    title: '欧盟 AI 法案 (EU AI Act) 合规落地指引',
    category: '合规政策',
    description: '监控通用目的 AI (GPAI) 透明度准则、高风险用例红线与合规审计技术框架',
    agent: 'LegalCompliance-Scanner',
    deepFilter: false,
    sources: [
      { icon: 'account_balance', label: 'EU Commission 官方公告' },
      { icon: 'gavel', label: '政策法案数据库' },
      { icon: 'domain', label: '法规解读智库' },
    ],
    updatedAt: '昨天 09:30',
    updatedDetail: '已完成日巡检',
    unreadLabel: '2 条未读',
    unreadTone: 'secondary',
    frequency: 'daily',
    active: true,
  },
  {
    id: 'quantum',
    title: '量子计算前沿与超导容错拓扑',
    category: '量子拓扑',
    description: '追踪表面码容错、量子比特相干时间突破、Nature/Science 前沿物理预印本',
    agent: 'Quantum-Preprint-Parser',
    deepFilter: false,
    sources: [
      { icon: 'science', label: 'Nature / Science' },
      { icon: 'biotech', label: 'Arxiv Quant-Ph' },
    ],
    updatedAt: '2 天前',
    updatedDetail: '周巡检已就绪',
    unreadLabel: '全部已读',
    unreadTone: 'muted',
    frequency: 'weekly',
    active: true,
  },
  {
    id: 'embodied-ai',
    title: '具身智能与人形机器人产业链',
    category: '机器人技术',
    description: '跟踪电机减速器、端到端视触觉大模型与具身关节硬件供应链',
    agent: '探针已休眠',
    deepFilter: false,
    sources: [
      { icon: 'pixel_7_pro', label: 'Patent RSS' },
      { icon: 'memory', label: 'IEEE Spectrum' },
      { icon: 'query_stats', label: '行业调研机构' },
    ],
    updatedAt: '3 天前',
    updatedDetail: '手动挂起',
    unreadLabel: '已暂停',
    unreadTone: 'muted',
    frequency: 'daily',
    active: false,
  },
]

export interface MetricCard {
  id: string
  label: string
  icon: string
  iconTone?: 'primary' | 'error' | 'default'
  value: string
  /** Sub-line shown next to the value (e.g. "/ 7 处于常驻激活"). */
  caption: string
  /** One optional accent (delta %, footer line, etc). */
  accent?: {
    kind: 'delta' | 'footer' | 'progress'
    text?: string
    /** ratio for progress kind */ ratio?: number
    /** Material icon name for `footer-icon` kind. */
    icon?: string
    /** Multiple text fragments with optional tone for `footer-parts` kind. */
    parts?: ReadonlyArray<{ text: string; tone?: 'primary' | 'secondary' }>
  }
}

export const METRICS: MetricCard[] = [
  {
    id: 'active',
    label: '活跃巡检主题',
    icon: 'radar',
    iconTone: 'primary',
    value: '5',
    caption: '/ 7 处于常驻激活',
    accent: { kind: 'progress', ratio: 5 / 7 },
  },
  {
    id: 'capture-24h',
    label: '24h 捕获情报条目',
    icon: 'stream',
    value: '1,429',
    caption: '+18.4%',
    accent: {
      kind: 'footer',
      icon: 'sensors',
      text: '平均置信度 score ≥ 0.88',
    },
  },
  {
    id: 'review',
    label: '待审阅高优情报',
    icon: 'mark_email_unread',
    iconTone: 'error',
    value: '19',
    caption: '条待合成提取',
    accent: { kind: 'footer', text: '3 份自动简报草稿生成中' },
  },
  {
    id: 'probes',
    label: '分布式探针状态',
    icon: 'hub',
    value: '14/14',
    caption: '节点满载巡检',
    accent: {
      kind: 'footer',
      parts: [
        { text: '平均响应: 240ms' },
        { text: 'HTTP 200', tone: 'primary' },
      ],
    },
  },
]

export interface PresetTemplate {
  id: string
  icon: string
  title: string
  description: string
  sourceCount: number
}

export const TEMPLATES: PresetTemplate[] = [
  {
    id: 'biotech',
    icon: 'biotech',
    title: '推荐模版: 生物医药分子生成',
    description:
      '预置 ChemRxiv、BioRxiv 预印本流，监控扩散模型在蛋白质对接与小分子生成中的最新突破。',
    sourceCount: 6,
  },
  {
    id: 'semi-supply',
    icon: 'candlestick_chart',
    title: '推荐模版: 全球宏观半导体供应链',
    description: '集成 TSMC 月度营收报表、ASML 极紫外光刻机订单流与各国出入境关税海关微观数据库。',
    sourceCount: 11,
  },
]

export interface AgentLogLine {
  time: string
  tag: 'DISPATCH' | 'FILTER' | 'SYNTH'
  message: string
  /** Tailwind class for tag colour (primary vs secondary). */
  tone: 'primary' | 'secondary'
}

export const AGENT_LOG: AgentLogLine[] = [
  { time: '10:44:02', tag: 'DISPATCH', tone: 'primary', message: '探针探测 "SEC 10-Q" (200 OK)' },
  { time: '10:44:15', tag: 'FILTER', tone: 'secondary', message: '排除 14 条冗余噪声与转载' },
  { time: '10:44:18', tag: 'SYNTH', tone: 'primary', message: '触发生成 Blackwell 算力推演树' },
]

export interface DrawerFrequencyOption {
  value: Frequency
  icon: string
  iconTone: 'primary' | 'secondary'
  label: string
  detail: string
}

export const DRAWER_FREQUENCIES: DrawerFrequencyOption[] = [
  { value: 'realtime', icon: 'bolt', iconTone: 'primary', label: '实时推送', detail: '≤ 5 分钟' },
  { value: '6h', icon: 'timelapse', iconTone: 'secondary', label: '每 6 小时', detail: '标准巡检' },
  {
    value: 'daily',
    icon: 'wb_sunny',
    iconTone: 'secondary',
    label: '每日晨报',
    detail: '08:00 汇总',
  },
  {
    value: 'weekly',
    icon: 'calendar_view_week',
    iconTone: 'secondary',
    label: '每周汇总',
    detail: '周一全量',
  },
]

export interface SourcePreset {
  id: string
  label: string
  detail: string
  defaultChecked: boolean
}

export const SOURCE_PRESETS: SourcePreset[] = [
  {
    id: 'arxiv',
    label: '学术预印本库',
    detail: 'Arxiv (cs.AI, cs.LG, Quant-ph)',
    defaultChecked: true,
  },
  {
    id: 'rss',
    label: '技术博客与官方 RSS',
    detail: 'OpenAI, DeepMind, Anthropic',
    defaultChecked: true,
  },
  {
    id: 'filings',
    label: '官方监管与上市公司财报',
    detail: 'SEC EDGAR, 欧盟公报数据库',
    defaultChecked: true,
  },
  {
    id: 'social',
    label: '专家推特与 Discord 讨论',
    detail: '高信誉核心工程师 List',
    defaultChecked: false,
  },
]
