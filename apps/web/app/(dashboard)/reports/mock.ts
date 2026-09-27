/**
 * Mock data for /reports — 1:1 with argus_reports/code.html.
 * Lives next to the route (per project convention).
 *
 * All shapes are `as const` so consumer switch/case inference is exhaustive
 * and the design-time `tone` / `status` literals stay narrow.
 */

export type TopicTone = 'primary' | 'secondary' | 'neutral' | 'fixed'
export type ReportStatus = 'verified' | 'running'

export interface ReportTopic {
  label: string
  tone: TopicTone
}

export interface Report {
  id: string
  title: string
  summary: string
  topic: ReportTopic
  generatedAt: string
  generatedAtSub: string
  sourcesCount: number
  viewsCount: number
  status: ReportStatus
  starred: boolean
  /** When status === "running", 0..100 progress indicator. */
  runningProgress?: number
  runningStage?: string
}

export interface MetricTile {
  id: string
  label: string
  value: string
  sub: string
  icon: string
  valueTone: 'default' | 'primary'
  subTone: 'success' | 'secondary'
}

export interface FilterTab {
  id: string
  label: string
  count: number
}

export type TopicFilterId =
  'ai-hardware' | 'frontier-model' | 'policy' | 'vc-trend' | 'green-energy' | 'frontier-tech'

export interface TopicFilter {
  id: TopicFilterId
  label: string
  count: number
  checked: boolean
}

export interface CitationScale {
  id: string
  label: string
  active: boolean
}

export interface PipelineStatusFilter {
  id: string
  label: string
  checked: boolean
}

export interface SortOption {
  id: string
  label: string
}

export interface TimeframeOption {
  id: string
  label: string
  active: boolean
}

/* ── Page header copy ─────────────────────────────────────────────── */

export const PAGE_TITLE = '研究报告库'
export const PAGE_TITLE_EN = 'RESEARCH REPOSITORY'
export const PAGE_SUBTITLE_PREFIX = '本月已由多智能体生成'
export const PAGE_SUBTITLE_REPORT_COUNT = '47'
export const PAGE_SUBTITLE_MID = '篇深度研报'
export const PAGE_SUBTITLE_TRACK_PREFIX = '覆盖'
export const PAGE_SUBTITLE_TRACK_COUNT = '12'
export const PAGE_SUBTITLE_TRACK_SUFFIX = '个技术与战略市场赛道'
export const PAGE_DAG_STATUS = 'DAG 持续监视中'

/* ── Top CTAs ─────────────────────────────────────────────────────── */

export const CTA_FILTER_LABEL = '多维筛选'
export const CTA_NEW_RESEARCH_LABEL = '发起新研究'
export const CTA_NEW_RESEARCH_SHORTCUT = '⌘N'

/* ── Metric strip (4 KPI tiles) ───────────────────────────────────── */

export const METRIC_TILES: ReadonlyArray<MetricTile> = [
  {
    id: 'verified',
    label: '已交叉验证深度报告',
    value: '42',
    sub: '89.3% 合格率',
    icon: 'verified',
    valueTone: 'default',
    subTone: 'success',
  },
  {
    id: 'pipeline',
    label: '实时流水线处理中',
    value: '3',
    sub: '47 节点处于运行态',
    icon: 'cyclone',
    valueTone: 'primary',
    subTone: 'secondary',
  },
  {
    id: 'citations',
    label: '平均学术与产业溯源',
    value: '26.4',
    sub: '权威源 / 篇',
    icon: 'database',
    valueTone: 'default',
    subTone: 'secondary',
  },
  {
    id: 'views',
    label: '组织内综合调阅',
    value: '1,482',
    sub: '较上周 +24%',
    icon: 'visibility',
    valueTone: 'default',
    subTone: 'success',
  },
]

/* ── Filter tabs ──────────────────────────────────────────────────── */

export const FILTER_TABS: ReadonlyArray<FilterTab> = [
  { id: 'all', label: '全部报告', count: 47 },
  { id: 'starred', label: '星标收藏', count: 12 },
  { id: 'shared', label: '已向团队共享', count: 8 },
  { id: 'archive', label: '历史归档', count: 5 },
]

/* ── Search input ─────────────────────────────────────────────────── */

export const SEARCH_PLACEHOLDER = '搜索报告标题、标签或智能体关键词...'
export const SEARCH_SHORTCUT = '⌘K'

/* ── Sort dropdown ────────────────────────────────────────────────── */

export const SORT_OPTIONS: ReadonlyArray<SortOption> = [
  { id: 'newest', label: '最新生成 (降序)' },
  { id: 'citations', label: '引用权威源最多' },
  { id: 'views', label: '调阅频次最高' },
  { id: 'depth', label: '研究深度星级' },
]

/* ── View switcher tooltips ───────────────────────────────────────── */

export const VIEW_TABLE_LABEL = '表格视图'
export const VIEW_GRID_LABEL = '网格卡片视图'

/* ── Filter drawer ────────────────────────────────────────────────── */

export const FILTER_DRAWER_TITLE = '多维指标筛选'
export const FILTER_DRAWER_RESET = '重置条件'

export const FILTER_TIMEFRAME_TITLE = '时间跨度 / Timeframe'
export const TIMEFRAME_OPTIONS: ReadonlyArray<TimeframeOption> = [
  { id: 'all', label: '全部周期', active: true },
  { id: '24h', label: '过去 24 小时', active: false },
  { id: '7d', label: '近 7 天', active: false },
  { id: 'mtd', label: '本月至今', active: false },
]

export const FILTER_TOPIC_TITLE = '课题研究赛道 / Topics'
export const TOPIC_FILTERS: ReadonlyArray<TopicFilter> = [
  { id: 'ai-hardware', label: 'AI 硬件与芯片架构', count: 14, checked: true },
  { id: 'frontier-model', label: '前沿模型与多模态', count: 12, checked: true },
  { id: 'policy', label: '政策法案与合规监管', count: 8, checked: false },
  { id: 'vc-trend', label: '风险投资与产业格局', count: 7, checked: false },
  { id: 'green-energy', label: '绿色能源与智算中心', count: 6, checked: false },
]

export const FILTER_CITATION_TITLE = '权威源规模 / Citation Scale'
export const CITATION_SCALES: ReadonlyArray<CitationScale> = [
  { id: '1-10', label: '1 - 10 篇', active: false },
  { id: '10-30', label: '10 - 30 篇 (标准)', active: true },
  { id: '30+', label: '30+ 篇 (宏观)', active: false },
]

export const FILTER_STATUS_TITLE = '流水线状态 / Pipeline Status'
export const PIPELINE_STATUSES: ReadonlyArray<PipelineStatusFilter> = [
  { id: 'verified', label: '已通过全部交叉验证', checked: true },
  { id: 'running', label: '智能体流式撰写中', checked: true },
  { id: 'attention', label: '异常需人工介入核实', checked: false },
]

export const CONFIDENCE_LABEL = '综合置信度均值'
export const CONFIDENCE_VALUE = '98.2%'
export const CONFIDENCE_NOTE = '基于多智能体交叉对撞机制，排除幻觉因子。'

/* ── Table column headers ─────────────────────────────────────────── */

export const TABLE_HEADER = {
  title: '标题与核心摘要',
  topic: '研究赛道',
  generatedAt: '生成时间',
  sources: '权威源',
  status: '状态 / 操作',
} as const

/* ── Reports (6 rows, matching design) ────────────────────────────── */

export const REPORTS: ReadonlyArray<Report> = [
  {
    id: 'rpt-001',
    title: 'NVIDIA H100 与 Blackwell 大模型推理架构对比：吞吐量与 TCO 深度分析',
    summary:
      '聚焦 FP4 精度缩放定律、NVLink 5 互联开销及万卡集群大规模 Serving 场景下的真实成本测算。',
    topic: { label: 'AI 硬件与芯片', tone: 'secondary' },
    generatedAt: '2 小时前',
    generatedAtSub: '10:24 生成',
    sourcesCount: 23,
    viewsCount: 142,
    status: 'verified',
    starred: true,
  },
  {
    id: 'rpt-002',
    title: 'Q3 全球 AI 大模型基础设施投融资与算力利用率研报',
    summary: '涵盖硅谷头部资本下注流向、GPU 租赁云市占率演进与 Neocloud 算力空置率监测数据。',
    topic: { label: '风险投资与趋势', tone: 'neutral' },
    generatedAt: '昨天 14:20',
    generatedAtSub: '自动化批跑',
    sourcesCount: 18,
    viewsCount: 329,
    status: 'verified',
    starred: false,
  },
  {
    id: 'rpt-003',
    title: '欧盟 AI 法案正式生效与高风险系统合规落地图谱',
    summary: '拆解通用目的模型 (GPAI) 透明度准则、技术红线罚则及全球跨国企业研发自查清单。',
    topic: { label: '政策与法律监管', tone: 'neutral' },
    generatedAt: '3 天前',
    generatedAtSub: '定向合规专项',
    sourcesCount: 31,
    viewsCount: 86,
    status: 'verified',
    starred: false,
  },
  {
    id: 'rpt-004',
    title: 'OpenAI 商业化与下一代前沿多模态推理模型策略深度解构',
    summary: '分析 System 2 强化学习推理阶段演化、API 阶梯定价策略及企业级 Agent 生态护城河。',
    topic: { label: '前沿模型与多模态', tone: 'fixed' },
    generatedAt: '1 周前',
    generatedAtSub: '高优先级调度',
    sourcesCount: 15,
    viewsCount: 512,
    status: 'verified',
    starred: true,
  },
  {
    id: 'rpt-005',
    title: '2026 全球气候科技与数据中心清洁能源投资分析',
    summary:
      '核裂变小型模块化反应堆 (SMR)、地热及储能方案在下一代千万瓦级超级数据中心的应用可行性。',
    topic: { label: '绿色能源与智算', tone: 'neutral' },
    generatedAt: '执行中 (DAG)',
    generatedAtSub: '阶段: 交叉反思层',
    sourcesCount: 42,
    viewsCount: 94,
    status: 'running',
    starred: false,
    runningProgress: 68,
    runningStage: '交叉反思层',
  },
  {
    id: 'rpt-006',
    title: '量子退火与超导容错量子计算产业路线图对比',
    summary: '涵盖逻辑量子比特纠错阈值、相干时间瓶颈突破及制药与组合优化工业化试点。',
    topic: { label: '前沿硬核科技', tone: 'neutral' },
    generatedAt: '3 周前',
    generatedAtSub: '外部专家评审完成',
    sourcesCount: 29,
    viewsCount: 204,
    status: 'verified',
    starred: true,
  },
]

/* ── Pagination ───────────────────────────────────────────────────── */

export const PAGE_SIZE = 6
export const TOTAL_REPORTS = 47
export const TOTAL_PAGES = 8
export const PAGINATION_PAGES: ReadonlyArray<number> = [1, 2, 3, 8]
export const PAGINATION_RANGE_FROM = 1
export const PAGINATION_RANGE_TO = 6

/* ── Bulk action bar ──────────────────────────────────────────────── */

export const BULK_ACTIONS = [
  { id: 'export', label: '批量导出 PDF', icon: 'picture_as_pdf' },
  { id: 'group', label: '归入集合', icon: 'folder' },
  { id: 'revalidate', label: '重新校验', icon: 'sync' },
  { id: 'archive', label: '批量归档', icon: 'delete', tone: 'danger' as const },
] as const

/* ── Top header copy ──────────────────────────────────────────────── */

export const TOPBAR_STATUS_LABEL = '就绪'
export const TOPBAR_THROUGHPUT = '8.2k tokens/s'

export const SIDEBAR_PRODUCT = 'Argus'
export const SIDEBAR_SUBTITLE = 'Synthesizer Core'
export const SIDEBAR_VERSION = 'v2.4'
export const SIDEBAR_WORKSPACE_LABEL = 'Argus Research Workspace'
export const SIDEBAR_NAV_LABEL = 'Navigation'

export const SIDEBAR_NAV: ReadonlyArray<{
  id: string
  label: string
  icon: string
  active?: boolean
  href: string
}> = [
  { id: 'dashboard', label: 'Dashboard 首页', icon: 'dashboard', href: '#' },
  {
    id: 'reports',
    label: '报告列表',
    icon: 'article',
    href: '#',
    active: true,
  },
  { id: 'topics', label: '主题订阅', icon: 'rss_feed', href: '#' },
  { id: 'sources', label: '资料库', icon: 'database', href: '#' },
  { id: 'settings', label: '设置', icon: 'tune', href: '#' },
]

export const SIDEBAR_CLUSTER_TITLE = 'Agent Run Cluster'
export const SIDEBAR_CLUSTER_STATUS = 'Active'
export const SIDEBAR_CLUSTER_DAG = 'DAG: 14 Nodes'
export const SIDEBAR_CLUSTER_LATENCY = '99.4% Latency'
export const SIDEBAR_CLUSTER_BAR_WIDTH = '66.6667%'
export const SIDEBAR_SESSION_LABEL = 'Session #AR-882'
