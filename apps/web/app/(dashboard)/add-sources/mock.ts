/**
 * Add Sources page mock data — ingestion queue.
 * Each item represents one ingestion task in the right-panel monitor.
 */

export type QueueKind = "pdf" | "html" | "audio" | "excel";

export interface QueueItem {
  id: string;
  name: string;
  kindLabel: string; // "PDF" / "Web HTML" / "Audio / Voice" / "Excel / Sheet"
  size: string;
  progressLabel: string; // "142/180 chunks" / "耗时 4.1s" / "Whisper-v3" / "Matrix Parse"
  progress: number; // 0-100
  statusLabel: string; // progress-bar caption
  timing?: string; // "3.2s" / "100%" / "14:20 / 34:10"
  iconName: string;
  iconAccent: "primaryFixed" | "surfaceHighest" | "errorContainer" | "onSurfaceVariant";
  done?: boolean; // if true, status pill = 已索引
  entities?: string; // "26 个知识实体节点已注入概念图谱"
  waveform?: boolean; // audio progress visual
  timeCurrent?: string; // audio: "14:20"
  timeTotal?: string; // audio: "34:10"
}

export const queueItems: QueueItem[] = [
  {
    id: "q-tesla",
    name: "tesla_q3_fy26_earnings_call.pdf",
    kindLabel: "PDF",
    size: "4.8 MB",
    progressLabel: "142/180 chunks",
    progress: 78,
    statusLabel: "正在执行双层向量嵌入 (text-embedding-3-large)",
    timing: "3.2s",
    iconName: "picture_as_pdf",
    iconAccent: "errorContainer",
  },
  {
    id: "q-openai",
    name: "openai_o3_reasoning_architecture_spec.html",
    kindLabel: "Web HTML",
    size: "340 KB",
    progressLabel: "耗时 4.1s",
    progress: 100,
    statusLabel: "26 个知识实体节点已注入概念图谱",
    timing: "100%",
    iconName: "html",
    iconAccent: "surfaceHighest",
    done: true,
    entities: "26 个知识实体节点已注入概念图谱",
  },
  {
    id: "q-tsmc-audio",
    name: "interview_tsmc_packaging_engineer.mp3",
    kindLabel: "Audio / Voice",
    size: "38.2 MB",
    progressLabel: "Whisper-v3",
    progress: 42,
    statusLabel: "正在执行多角色声纹分离与时间戳对齐...",
    timing: "14:20 / 34:10",
    iconName: "graphic_eq",
    iconAccent: "primaryFixed",
    waveform: true,
    timeCurrent: "14:20",
    timeTotal: "34:10",
  },
  {
    id: "q-semianalysis-xlsx",
    name: "semianalysis_foundry_cost_model.xlsx",
    kindLabel: "Excel / Sheet",
    size: "1.2 MB",
    progressLabel: "Matrix Parse",
    progress: 15,
    statusLabel: "正在提取单元格层级并构建多维财务指标关系...",
    timing: undefined,
    iconName: "table_chart",
    iconAccent: "onSurfaceVariant",
  },
];

export const defaultTopicOptions = [
  { value: "topic-1", label: "NVIDIA 算力演进与超节点架构" },
  { value: "topic-2", label: "前沿多模态推理与具身智能" },
  { value: "topic-3", label: "全球半导体先进封装与供应链" },
  { value: "topic-4", label: "暂不归档 (公共向量库)" },
];

export const processingOptions = [
  {
    title: "深度提取图表与公式",
    meta: "Nougat OCR + LaTeX 语法数理结构还原",
  },
  {
    title: "智能体生成执行摘要",
    meta: "提取核心论点、因果链与关键预测指标",
  },
  {
    title: "语义多粒度切片",
    meta: "512 + 2048 token 混合双层向量化索引",
  },
  {
    title: "自动研报课题匹配打标",
    meta: "识别行业实体并映射至内部概念图谱",
  },
];

export const queueSummary = {
  total: 4,
  capacity: "5 线程池",
  etaSeconds: "1分20秒",
  gpuLoad: "34%",
};