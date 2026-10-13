/**
 * Mock data for /explore (argus_2 design restoration).
 *
 * Real shapes only — no fabricated execution semantics. Each piece mirrors
 * one section of the design so a component can swap in any other source
 * later without reshaping.
 */

import type { ReferenceV } from '@/lib/api/sse'

export type NodeLifecycle = 'completed' | 'active' | 'pending'

export interface AgentNode {
  /** Stable id used for React keys + click routing. */
  id: string
  /** Display label (Chinese). */
  name: string
  /** One-line role description; muted gray. */
  role: string
  /** Current lifecycle. Drives circle style + rail highlight. */
  lifecycle: NodeLifecycle
  /** Wall-clock duration string (e.g. "1.2s", "运行中 4.4s", "排队中"). */
  latency: string
  /** Token count string (e.g. "1.1k tokens"). */
  tokens: string
}

export interface ToolCall {
  id: string
  name: string
  /** Compact args preview shown truncated. */
  args: string
  duration: string
}

/**
 * 引用条目。直接复用后端契约（`lib/api/sse.ts` 的 `ReferenceV`），
 * 不另立一套展示形状——mock 与实时数据必须同构，否则角标在流式模式下
 * 渲染不出来。
 */
export type Citation = ReferenceV

export interface RawJsonState {
  agent_id: string
  status: string
  session_id: string
  step_index: number
  telemetry: {
    execution_time_ms: number
    input_tokens: number
    output_tokens: number
    model: string
  }
  claims_derived: Array<{
    claim: string
    confidence: number
    source_ids?: string[]
    model_type?: string
  }>
  intermediate_context: {
    nvlink_bandwidth: string
    fp4_quantization_drift: string
    cooling_requirement: string
  }
}

/* ────────────── DAG nodes (top → bottom) ────────────── */

export const AGENT_NODES: AgentNode[] = [
  {
    id: 'supervisor',
    name: '主管智能体 (Supervisor)',
    role: '查询意图拆解与提示词合成',
    lifecycle: 'completed',
    latency: '1.2s',
    tokens: '1.1k tokens',
  },
  {
    id: 'researcher',
    name: '调研智能体 (Researcher)',
    role: '已抓取 14 篇权威技术报告与基准测试',
    lifecycle: 'completed',
    latency: '6.8s',
    tokens: '4.3k tokens',
  },
  {
    id: 'analyst',
    name: '分析智能体 (Analyst)',
    role: '正在计算 FP4 / FP8 吞吐比率与总拥有成本 (TCO)',
    lifecycle: 'active',
    latency: '运行中 4.4s',
    tokens: '2.8k tokens',
  },
  {
    id: 'writer',
    name: '撰写智能体 (Writer)',
    role: '正在流式生成对比 Markdown 研报',
    lifecycle: 'pending',
    latency: '排队中',
    tokens: '0 tokens',
  },
  {
    id: 'critic',
    name: '审阅智能体 (Critic)',
    role: '基于数据源遥测指标进行交叉验证',
    lifecycle: 'pending',
    latency: '排队中',
    tokens: '0 tokens',
  },
]

/* ────────────── DAG header stats ────────────── */

export const DAG_STATS = {
  title: '智能体执行有向无环图 (DAG)',
  pipeline: 'linear_pipeline_v4',
  currentStep: 3,
  totalSteps: 5,
  elapsed: '12.4秒',
  tokens: '8.2k 标记',
}

/* ────────────── Streaming report content ────────────── */

export const REPORT_QUERY = '对比 NVIDIA H100 与 Blackwell 在大模型推理中的表现'

export const REPORT_TITLE = 'NVIDIA H100 与 Blackwell 大模型推理架构对比：吞吐量与 TCO 深度分析'

export interface MetricColumn {
  label: string
  headline: string
  detail: string
  highlight?: boolean
}

export const HARDWARE_METRICS: MetricColumn[] = [
  {
    label: 'H100 SXM (Hopper)',
    headline: '1,979 TFLOPS',
    detail: 'FP8 张量核心 · 80GB HBM3',
  },
  {
    label: 'B200 (Blackwell)',
    headline: '9,000 TFLOPS',
    detail: 'FP4 张量核心 · 192GB HBM3e',
    highlight: true,
  },
  {
    label: 'GB200 NVL72 机架',
    headline: '30x Token 推理加速',
    detail: '130TB/s NVLink 互联域',
  },
]

/* ────────────── Inspector: tool calls + raw state ────────────── */

export const TOOL_CALLS: ToolCall[] = [
  {
    id: 'tco',
    name: 'tco_calculator',
    args: '{ cluster_qps: 100000, model: "llama-3-70b", target_latency: "20ms" }',
    duration: '182ms',
  },
  {
    id: 'bench',
    name: 'benchmark_fetch',
    args: '{ arch: ["h100_sxm", "b200_nvl72"], metric: "fp4_vs_fp8_tflops" }',
    duration: '340ms',
  },
]

export const TRACE_ID = 'PHOENIX TRACE #8932'

export const ANALYST_RAW_STATE: RawJsonState = {
  agent_id: 'agent_analyst_04',
  status: 'executing',
  session_id: 'sess_blackwell_vs_h100',
  step_index: 3,
  telemetry: {
    execution_time_ms: 4410,
    input_tokens: 1840,
    output_tokens: 980,
    model: 'claude-3-5-sonnet-20241022',
  },
  claims_derived: [
    {
      claim: 'Blackwell 在 FP4 精度下可实现高达 4 倍推理吞吐提升',
      confidence: 0.96,
      source_ids: ['NVIDIA-WP-2024', 'ANAND-B200-MAR24'],
    },
    {
      claim: '在 10 万 QPS 集群规模下预计减少 75% TCO 综合能耗',
      confidence: 0.91,
      model_type: 'datacenter_amortized_kwh',
    },
  ],
  intermediate_context: {
    nvlink_bandwidth: '单 GPU 双向 1.8TB/s',
    fp4_quantization_drift: 'MMLU 精度漂移 <0.8%',
    cooling_requirement: '单机架芯片直触液冷 120kW',
  },
}

/* ────────────── Citations (anchored to [n] superscripts) ────────────── */

export const CITATIONS: Citation[] = [
  {
    n: 1,
    chunk_id: 4211,
    source_id: 17,
    chunk_index: 8,
    page: 12,
    title: 'NVIDIA 技术白皮书：Blackwell GPU 架构深度剖析',
    excerpt: '在 FP8 精度下，Blackwell 的单卡吞吐相较 H100 提升约 3.5 倍，NVLink 域带宽达 130TB/s。',
    recall: '向量+BM25',
  },
  {
    n: 2,
    chunk_id: 4212,
    source_id: 17,
    chunk_index: 9,
    page: 14,
    title: 'AnandTech 深度解析：NVIDIA Blackwell B200 双芯架构与 NVLink 5',
    excerpt: 'B200 采用双 die 设计与 10TB/s HBM3e，单机架 NVL72 提供 1.8 万亿参数级 MoE 权重承载能力。',
    recall: '向量',
  },
  {
    n: 3,
    chunk_id: 3790,
    source_id: 22,
    chunk_index: 2,
    page: null,
    title: '路透社：超大规模云厂商加速推进 Blackwell 集群部署用于 Gemini 与 ChatGPT',
    excerpt: '多家超大规模云厂商确认已在生产环境部署 Blackwell 集群，主要面向大参数 MoE 模型的在线推理。',
    recall: 'BM25',
  },
]

/* ────────────── Slash commands (popover) ────────────── */

export interface SlashCommand {
  cmd: string
  description: string
}

export const SLASH_COMMANDS: SlashCommand[] = [
  { cmd: '/research', description: '深度全网检索' },
  { cmd: '/compare', description: '硬件参数矩阵' },
  { cmd: '/summarize', description: '核心结论摘要' },
]

/* ────────────── TopBar ────────────── */

export const SESSION_BREADCRUMB = 'sess_blackwell_vs_h100'
export const MODEL_BADGE = 'Claude Sonnet 5'
