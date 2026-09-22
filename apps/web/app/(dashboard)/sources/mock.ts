/**
 * Sources page mock data — RAG vector hub.
 * Each row matches the design intent: type / chunks / status / progress.
 */

export type SourceStatus = "ready" | "processing" | "live" | "failed";

export type SourceKind = "PDF" | "URL" | "DOCX" | "RSS Feed" | "Arxiv/Data";

export interface SourceRow {
  id: string;
  title: string;
  meta: string; // SHA / URL / subtitle
  kind: SourceKind;
  size: string;
  chunks: string; // e.g. "87 Chunks" or "实时流动"
  citations: number;
  status: SourceStatus;
  /** 0-100 numeric progress; only meaningful for "processing" */
  progress?: number;
  timeLabel: string; // "2 小时前"
  /** Optional accent class on the kind icon tile */
  iconAccent: "red" | "blue" | "amber" | "purple" | "primary";
  iconName: string;
}

export const sourceRows: SourceRow[] = [
  {
    id: "src-nvidia-q2",
    title: "NVIDIA Q2 FY26 季度财报与高管电话会纪要.pdf",
    meta: "SHA256: 9b2d87e04... · 官方IR投资人关系披露",
    kind: "PDF",
    size: "4.2 MB",
    chunks: "87 Chunks (切片)",
    citations: 14,
    status: "ready",
    timeLabel: "2 小时前",
    iconAccent: "red",
    iconName: "picture_as_pdf",
  },
  {
    id: "src-amd-mi300x",
    title: "AMD Instinct MI300X 架构设计与性能技术白皮书.pdf",
    meta: "CDNA3 架构分析 · ROCm 6.2 算子兼容表",
    kind: "PDF",
    size: "8.1 MB",
    chunks: "142 Chunks (切片)",
    citations: 9,
    status: "ready",
    timeLabel: "昨天",
    iconAccent: "red",
    iconName: "picture_as_pdf",
  },
  {
    id: "src-semianalysis-blackwell",
    title: "Semianalysis: Blackwell TCO 深度拆解与晶圆利用率.html",
    meta: "https://semianalysis.com/blackwell-cost-model",
    kind: "URL",
    size: "184 KB",
    chunks: "26 Chunks (切片)",
    citations: 23,
    status: "ready",
    timeLabel: "2 天前",
    iconAccent: "blue",
    iconName: "public",
  },
  {
    id: "src-mlcommons",
    title: "MLCommons v4.1 推理基准性能评测官方原始数据集",
    meta: "MLPerf Inference Benchmark Reports · JSON/Parquet",
    kind: "Arxiv/Data",
    size: "1.8 MB",
    chunks: "58 Chunks (切片)",
    citations: 7,
    status: "ready",
    timeLabel: "3 天前",
    iconAccent: "amber",
    iconName: "dataset",
  },
  {
    id: "src-eu-ai-act",
    title: "欧盟 AI 法案 (EU AI Act) 全文合规要求实施细则条例.pdf",
    meta: "欧盟公报 EUR-Lex 2024/1689 法律终稿条文",
    kind: "PDF",
    size: "12.6 MB",
    chunks: "310 Chunks (切片)",
    citations: 18,
    status: "ready",
    timeLabel: "5 天前",
    iconAccent: "red",
    iconName: "picture_as_pdf",
  },
  {
    id: "src-hackernews-rss",
    title: "Hacker News & arXiv cs.AI 前沿实时论文流",
    meta: "轮询周期: 5m · 自动化预清洗与 Token 蒸馏",
    kind: "RSS Feed",
    size: "实时流动",
    chunks: "3,420 条目",
    citations: 42,
    status: "live",
    timeLabel: "10分钟前更新",
    iconAccent: "purple",
    iconName: "rss_feed",
  },
  {
    id: "src-tsmc-2nm",
    title: "TSMC 2nm 制程节点与 CoWoS 封装良率调查备忘录.docx",
    meta: "内部访谈记录 · 晶圆代工产能分配估计",
    kind: "DOCX",
    size: "2.1 MB",
    chunks: "44 Chunks (预计)",
    citations: 0,
    status: "processing",
    progress: 78,
    timeLabel: "15 分钟前",
    iconAccent: "blue",
    iconName: "description",
  },
];

export const sourceStats = {
  total: 847,
  totalSize: "12.4 GB",
};