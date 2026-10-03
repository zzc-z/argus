/**
 * Mock data for `/report` — 1:1 extracted from argus_report_detail/code.html.
 *
 * Shape is intentionally flat (no nested API responses) so page-level
 * components can destructure directly. If real API lands, swap this file
 * for a typed fetch — keep the same exported names.
 */

export interface ReportMeta {
  id: string
  title: string
  tags: string[]
  dagSha: string
  generatedHoursAgo: number
  agentCount: number
  citationCount: number
  tokenCostK: number
  confidencePct: number
}

export interface ViewTab {
  key: ViewKey
  label: string
  icon: string
}

export type ViewKey = 'report' | 'comparison' | 'timeline' | 'decision'

export const reportMeta: ReportMeta = {
  id: 'REP-2025-084B',
  title: 'NVIDIA H100 与 Blackwell 大模型推理架构对比：吞吐量与 TCO 深度分析',
  tags: ['AI 硬件与芯片架构', 'NVIDIA', '推理加速', '基准评测'],
  dagSha: '8f9a2e',
  generatedHoursAgo: 2,
  agentCount: 5,
  citationCount: 23,
  tokenCostK: 12.4,
  confidencePct: 98.2,
}

export const viewTabs: ViewTab[] = [
  { key: 'report', label: '深度研报 (Report)', icon: 'article' },
  { key: 'comparison', label: '横向对比矩阵 (Comparison Table)', icon: 'table_chart' },
  { key: 'timeline', label: '技术演进时间线 (Timeline)', icon: 'timeline' },
  { key: 'decision', label: '决策行动清单 (Decision List)', icon: 'checklist' },
]

export interface CitationRef {
  id: string
  surface: string
  sourceTitle: string
  sourceAuthority: number
  sourceMatchPct: number
}

export const citations: CitationRef[] = [
  {
    id: '1',
    surface: '1',
    sourceTitle: 'NVIDIA Blackwell Architecture Technical Brief v1.4',
    sourceAuthority: 9.9,
    sourceMatchPct: 96,
  },
  {
    id: '2',
    surface: '2',
    sourceTitle: 'GB200 NVL72 Rack Architecture & Thermal Solutions',
    sourceAuthority: 9.8,
    sourceMatchPct: 93,
  },
  {
    id: '3',
    surface: '3',
    sourceTitle: 'MLPerf Inference v4.1 Benchmark Results & MoE Serving',
    sourceAuthority: 9.7,
    sourceMatchPct: 95,
  },
  {
    id: '4',
    surface: '4',
    sourceTitle: 'SemiAnalysis: Blackwell TCO & Foundry Wafer Allocation',
    sourceAuthority: 9.5,
    sourceMatchPct: 91,
  },
]

export type ChapterBlock =
  | { kind: 'p'; text: string; citationIds?: string[] }
  | { kind: 'callout'; headline: string; body: string }

export interface Chapter {
  id: string
  number: string
  title: string
  meta?: string
  blocks: ChapterBlock[]
}

export const chapter1: Chapter = {
  id: 'ch-1-summary',
  number: '01',
  title: '执行摘要 (Executive Summary)',
  meta: '阅读耗时 4 分钟',
  blocks: [
    {
      kind: 'callout',
      headline: '核心结论：FP4 张量核心与全机架液冷是 Blackwell 颠覆性降本的基石',
      body: '相较于 Hopper (H100) 架构，Blackwell (B200 / GB200 NVL72) 实现了从粗粒度 FP8 向微缩放格式 (Microscaling Formats) 原生 FP4 精度的质变跃迁。配合第五代 NVLink 提供的 1.8 TB/s 双芯互联与机架级 130 TB/s 全域交换带宽，在千亿级 MoE 与百亿级 Dense 模型推理中，单位 Token 生成能耗降低达 75%，集群综合 TCO 预期下降 42.6%。',
    },
    {
      kind: 'p',
      text: '进入 2024–2025 年，前沿大语言模型（LLM）的算力瓶颈已从「纯算力密集型预训练」迅速转变为「超低延迟、高并发吞吐量的实时推理（Serving）」。在这一工程拐点上，NVIDIA 推出的 Blackwell 架构不再单纯依赖先进制程缩放，而是依托 2080 亿晶体管双 Die 缝合封装与第二代 Transformer Engine 驱动的微缩放格式 (Microscaling) 技术。',
      citationIds: ['1'],
    },
    {
      kind: 'p',
      text: '研究团队通过对 23 篇官方白皮书与业界首发测试基准（MLPerf Inference v4.1）的数据拟合表明，GB200 NVL72 凭借液冷单机架 72 颗 GPU 的一体化拓扑，消除了跨节点 InfiniBand/以太网网络调度的通信气泡。对于长上下文窗口（32k-128k context）与多轮对话系统，该架构能够实现高达 30 倍的交互吞吐量飞跃。',
      citationIds: ['2'],
    },
  ],
}

export interface SpecRow {
  metric: string
  h100: string
  b200: string
  rack: string
  rackHighlight?: boolean
  b200Tinted?: boolean
}

export const specRows: SpecRow[] = [
  {
    metric: '制程工艺 (Process)',
    h100: 'TSMC 4N (单 Die)',
    b200: 'TSMC 4NP (双 Die CoWoS-L)',
    rack: '72x B200 + 36x Grace CPU',
    rackHighlight: true,
    b200Tinted: true,
  },
  {
    metric: '晶体管数量 (Transistors)',
    h100: '800 亿 (80B)',
    b200: '2,080 亿 (208B)',
    rack: '15 万亿+ (机架总合)',
    rackHighlight: true,
    b200Tinted: true,
  },
  {
    metric: '密集 FP8 峰值算力',
    h100: '1,979 TFLOPS',
    b200: '4,500 TFLOPS (2.27x)',
    rack: '360 PFLOPS',
    rackHighlight: true,
    b200Tinted: true,
  },
  {
    metric: '密集 FP4 极速算力',
    h100: '不支持 (需软仿真)',
    b200: '9,000 TFLOPS (原生)',
    rack: '720 PFLOPS',
    rackHighlight: true,
    b200Tinted: true,
  },
  {
    metric: '高带宽显存容量 (HBM)',
    h100: '80 GB HBM3',
    b200: '192 GB HBM3e (2.4x)',
    rack: '13.8 TB 全共享',
    rackHighlight: true,
    b200Tinted: true,
  },
  {
    metric: '显存总带宽 (Memory BW)',
    h100: '3.35 TB/s',
    b200: '8.0 TB/s (2.38x)',
    rack: '576 TB/s',
    rackHighlight: true,
    b200Tinted: true,
  },
  {
    metric: '节点互联总线 (NVLink)',
    h100: '900 GB/s (Gen 4)',
    b200: '1.8 TB/s (Gen 5)',
    rack: '130 TB/s 铜缆总线',
    rackHighlight: true,
    b200Tinted: true,
  },
  {
    metric: '标称散热功率 (TDP)',
    h100: '700W (风冷/液冷可选)',
    b200: '1,000W - 1,200W',
    rack: '~120 kW (整机架纯液冷)',
    rackHighlight: true,
    b200Tinted: true,
  },
]

export interface BenchmarkBar {
  label: string
  pct: number
  valueLabel: string
  tone: 'muted' | 'primary'
  emphasize?: boolean
}

export interface BenchmarkCard {
  id: string
  title: string
  subtitle: string
  envLine: string
  tailStat: string
  bars: BenchmarkBar[]
}

export const benchmarks: BenchmarkCard[] = [
  {
    id: 'bm-llama3',
    title: 'Llama 3 70B 推理吞吐',
    subtitle: 'BS=256 / 4k 序列',
    envLine: '基准环境：vLLM v0.6.2 Engine',
    tailStat: 'P99 TTFT: 18ms',
    bars: [
      { label: 'H100 SXM 80GB (FP8)', pct: 28, valueLabel: '1,240 T/s', tone: 'muted' },
      {
        label: 'B200 192GB (FP4 Microscale)',
        pct: 100,
        valueLabel: '4,480 T/s (3.6x)',
        tone: 'primary',
        emphasize: true,
      },
    ],
  },
  {
    id: 'bm-mixtral',
    title: 'Mixtral 8x22B MoE 吞吐',
    subtitle: 'BS=128 / 8k 序列',
    envLine: '基准环境：TensorRT-LLM 0.12',
    tailStat: 'MoE 跨卡通讯减损 81%',
    bars: [
      { label: 'H100 SXM 80GB (FP8)', pct: 22, valueLabel: '890 T/s', tone: 'muted' },
      {
        label: 'B200 192GB (FP4 Microscale)',
        pct: 96,
        valueLabel: '4,120 T/s (4.6x)',
        tone: 'primary',
        emphasize: true,
      },
    ],
  },
]

export interface TcoCard {
  id: string
  label: string
  value: string
  badge: string
  badgeTone: 'success' | 'primary' | 'muted'
  caption: string
}

export const tcoCards: TcoCard[] = [
  {
    id: 'tco-per-mtok',
    label: '每百万 Token 综合成本',
    value: '$0.0034',
    badge: '-62.8%',
    badgeTone: 'success',
    caption: 'H100 对应单价为 $0.0092/1M Tokens',
  },
  {
    id: 'tco-rack-ratio',
    label: '机架占地面积节省',
    value: '1 : 4.5',
    badge: '空间利用率',
    badgeTone: 'primary',
    caption: '等效 72 卡算力替代 320 张 H100',
  },
  {
    id: 'tco-pue',
    label: '数据中心 PUE 优化',
    value: '1.12',
    badge: '液冷直触',
    badgeTone: 'muted',
    caption: '较传统风冷数据中心 PUE 1.45 节电 22%',
  },
]

export const tcoCallout = {
  headline: '架构师采纳建议 (Architect Recommendation)',
  body: '若您的业务主力承载 30B 以上级别的 LLM / 多模态推理集群，且日均调用量突破 5 亿 Tokens，建议直接采用 GB200 NVL72 机架级部署方案；若现有 IDC 机房完全不具备高压液冷 CDU 改装条件，则过渡期内继续采购风冷 H200 (141GB HBM3e) 属于稳健风控策略。',
}

export interface Source {
  id: string
  indexLabel: string
  category: string
  title: string
  authority: number
  matchPct: number
  author: string
}

export const sources: Source[] = [
  {
    id: 'src-1',
    indexLabel: '[1]',
    category: '官方白皮书',
    title: 'NVIDIA Blackwell Architecture Technical Brief v1.4',
    authority: 9.9,
    matchPct: 96,
    author: 'NVIDIA Deep Learning Systems Team',
  },
  {
    id: 'src-2',
    indexLabel: '[2]',
    category: '官方架构手册',
    title: 'GB200 NVL72 Rack Architecture & Thermal Solutions',
    authority: 9.8,
    matchPct: 93,
    author: 'NVIDIA Systems Whitepaper (May 2024)',
  },
  {
    id: 'src-3',
    indexLabel: '[3]',
    category: '学术基准评测',
    title: 'MLPerf Inference v4.1 Benchmark Results & MoE Serving',
    authority: 9.7,
    matchPct: 95,
    author: 'MLCommons Research Group',
  },
  {
    id: 'src-4',
    indexLabel: '[4]',
    category: '深度分析测算',
    title: 'SemiAnalysis: Blackwell TCO & Foundry Wafer Allocation',
    authority: 9.5,
    matchPct: 91,
    author: 'Dylan Patel, Chief Analyst',
  },
]

export interface AgentStep {
  id: string
  initial: string
  name: string
  detail: string
  durationS: number
}

export const agents: AgentStep[] = [
  {
    id: 'ag-1',
    initial: 'S',
    name: '主管智能体 (Supervisor)',
    detail: '意图拆解与提示词合成',
    durationS: 0.8,
  },
  {
    id: 'ag-2',
    initial: 'R',
    name: '调研智能体 (Researcher)',
    detail: '抓取 23 篇权威白皮书',
    durationS: 4.2,
  },
  {
    id: 'ag-3',
    initial: 'A',
    name: '分析智能体 (Analyst)',
    detail: '计算 FP4/FP8 吞吐与 TCO',
    durationS: 3.6,
  },
  {
    id: 'ag-4',
    initial: 'W',
    name: '撰写智能体 (Writer)',
    detail: '流式合成学术级结构研报',
    durationS: 6.1,
  },
  {
    id: 'ag-5',
    initial: 'C',
    name: '审阅智能体 (Critic)',
    detail: '跨信源对抗性校验通过',
    durationS: 2.2,
  },
]

export const agentSummary = {
  totalDurationS: 16.9,
  successfulNodes: 5,
  totalNodes: 5,
  verifyPct: 100,
}

export interface RelatedReport {
  id: string
  category: string
  recency: string
  matchPct: number
  title: string
  meta: string
}

export const relatedReports: RelatedReport[] = [
  {
    id: 'rel-1',
    category: '基础设施投融资',
    recency: '昨天',
    matchPct: 94,
    title: '2025 全球超大规模算力中心液冷机架改造招标白皮书',
    meta: '4 个智能体 · 18 篇引用',
  },
  {
    id: 'rel-2',
    category: '竞品实测',
    recency: '3 天前',
    matchPct: 89,
    title: 'AMD Instinct MI300X 与 ROCm 6.2 在 Llama 3 微调基准评测',
    meta: '6 个智能体 · 31 篇引用',
  },
]

/* ──────────────────────────────────────────────────────────────────────
 * Phase 2 additions — Comparison / Timeline / Decision view data
 * Pre-Next 16 typedRoutes-safe export shape; consumed by page.tsx switch.
 * ────────────────────────────────────────────────────────────────────── */

export interface TimelineEvent {
  id: string
  date: string // 'YYYY.MM' or 'YYYY'
  category: 'architecture' | 'process' | 'interconnect' | 'ecosystem' | 'regulatory'
  title: string
  summary: string
  citationIds: string[]
}

export const timelineEvents: TimelineEvent[] = [
  {
    id: 'tl-1',
    date: '2022.10',
    category: 'architecture',
    title: 'Hopper H100 SXM 全面投产',
    summary: 'TSMC 4N 单 Die、800 亿晶体管、FP8 首次原生支持；NVLink Gen 4 900 GB/s 互联落地。',
    citationIds: ['1'],
  },
  {
    id: 'tl-2',
    date: '2023.07',
    category: 'interconnect',
    title: 'NVLink Switch 1 代外置化',
    summary: '跨节点 NVLink 域扩张为 64 颗 GPU；InfiniBand 在多轮对话系统中仍占主导。',
    citationIds: [],
  },
  {
    id: 'tl-3',
    date: '2024.03',
    category: 'process',
    title: 'Blackwell 双 Die CoWoS-L 量产',
    summary: 'TSMC 4NP 双芯缝合封装，2,080 亿晶体管；首次原生 FP4 Microscaling 张量核心。',
    citationIds: ['1'],
  },
  {
    id: 'tl-4',
    date: '2024.09',
    category: 'architecture',
    title: 'B200 / GB200 NVL72 整机架发布',
    summary: '72 颗 GPU + 36 颗 Grace CPU；1.8 TB/s NVLink Gen 5；整机架 130 TB/s 全域交换。',
    citationIds: ['1', '2'],
  },
  {
    id: 'tl-5',
    date: '2024.12',
    category: 'ecosystem',
    title: 'MLPerf Inference v4.1 Blackwell 端到端领先',
    summary: 'Llama 3 70B / Mixtral 8x22B 单卡等效吞吐刷新记录；液冷机架整体 TCO 拐点显现。',
    citationIds: ['3'],
  },
  {
    id: 'tl-6',
    date: '2025.03',
    category: 'regulatory',
    title: '美国 BIS 出口管制清单再升级',
    summary: 'H100/B200 在中国区新增许可要求；客户向 Hopper SXM 旧库存回流 12%。',
    citationIds: [],
  },
  {
    id: 'tl-7',
    date: '2025.06',
    category: 'architecture',
    title: 'GB300 / NVL72 第二代 Blackwell Ultra',
    summary: 'FP4 算力再 +50%、HBM3e 升级至 288GB；机架功耗维持 120kW 液冷范围。',
    citationIds: ['1'],
  },
  {
    id: 'tl-8',
    date: '2026.01',
    category: 'architecture',
    title: 'Rubin / Rubin Ultra (预期)',
    summary: '下一代架构（基于公开 roadmap）：HBM4、第三代 Transformer Engine；预计 2026H2 量产。',
    citationIds: [],
  },
]

export type DecisionPriority = 'critical' | 'high' | 'medium' | 'low'
export type DecisionStatus = 'pending' | 'in_progress' | 'shipped' | 'blocked'

export interface DecisionItem {
  id: string
  priority: DecisionPriority
  status: DecisionStatus
  action: string
  owner: string
  confidencePct: number
  impact: string
  rollbackCost: string
  citeIds: string[]
}

export const decisionItems: DecisionItem[] = [
  {
    id: 'dec-1',
    priority: 'critical',
    status: 'in_progress',
    action: '优先采购 GB200 NVL72 整机架',
    owner: '基础设施组 / 林涛',
    confidencePct: 92,
    impact: '单位推理成本 ↓ 42.6%；机柜功耗 ↑ 至 120kW 需液冷改造',
    rollbackCost: '高（机柜与冷却一次性投入 380 万）',
    citeIds: ['4'],
  },
  {
    id: 'dec-2',
    priority: 'high',
    status: 'pending',
    action: '对 Hopper H100 集群实施 MoE Serving 优化',
    owner: '平台组 / 张敏',
    confidencePct: 78,
    impact: '等效吞吐 ↑ 1.8x，无需新硬件投入',
    rollbackCost: '极低（仅配置回滚）',
    citeIds: ['3'],
  },
  {
    id: 'dec-3',
    priority: 'high',
    status: 'pending',
    action: '建立液冷机房容量预算 30 天前 commit 机制',
    owner: '运维组 / 陈航',
    confidencePct: 85,
    impact: '规避液冷改造排队（通常 8-12 周）',
    rollbackCost: '无（流程变更）',
    citeIds: [],
  },
  {
    id: 'dec-4',
    priority: 'medium',
    status: 'shipped',
    action: '引入 AMD MI300X 作为二级推理备选',
    owner: '采购组 / 周欣',
    confidencePct: 71,
    impact: '高优先级租户冗余方案；ROCm 6.2 兼容度约 65%',
    rollbackCost: '中（备选组件化）',
    citeIds: [],
  },
  {
    id: 'dec-5',
    priority: 'low',
    status: 'blocked',
    action: '评估 Rubin / Rubin Ultra 升级路径',
    owner: '架构组 / Thomas Lin',
    confidencePct: 54,
    impact: '2026H2 后增量 ~25% 单位成本',
    rollbackCost: '无（暂不行动）',
    citeIds: [],
  },
]

/** 提供按 id 解析的详情 mock。当前只有一个真实报告，所有 rpt-* 与外部
 *  ID 都映射到 REP-2025-084B（避免列表点击 404）。 */
export function provideReportById(id: string): {
  meta: ReportMeta
} {
  // 简单策略：未知 id 一律回落到默认。后续接 API 时改成 fetch + cache。
  void id
  return { meta: reportMeta }
}
