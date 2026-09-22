/**
 * Settings page mock data.
 *
 * Shape source: `argus_settings/code.html` (1:1 extraction).
 * All values are immutable seed data; client components hold the editable state.
 */

/* ── Left navigation ──────────────────────────────────────────────────── */

export type SettingsNavId =
  | "profile"
  | "memory"
  | "api-keys"
  | "prompts"
  | "tools"
  | "quota"
  | "danger";

export interface SettingsNavItem {
  id: SettingsNavId;
  label: string;
  hint: string;
  icon: string;
  danger?: boolean;
}

export const settingsNavItems: readonly SettingsNavItem[] = [
  { id: "profile", label: "个人资料", hint: "Profile", icon: "badge" },
  { id: "memory", label: "记忆与偏好", hint: "Active", icon: "psychology" },
  { id: "api-keys", label: "模型与 API 密钥", hint: "Keys", icon: "key" },
  { id: "prompts", label: "智能体提示词模版", hint: "Prompts", icon: "terminal" },
  { id: "tools", label: "第三方工具集成", hint: "Tools", icon: "hub" },
  { id: "quota", label: "订阅与算力配额", hint: "Quota", icon: "credit_card" },
  { id: "danger", label: "安全与危险区域", hint: "Danger", icon: "warning", danger: true },
] as const;

/** Vector index diagnostic card under the nav (design §67-79). */
export interface VectorIndexDiagnostic {
  label: string;
  statusLabel: string;
  statusTone: "primary";
  used: number;
  total: number;
  ratio: number;
}

export const vectorIndexDiagnostic: VectorIndexDiagnostic = {
  label: "向量索引状态",
  statusLabel: "HNSW-Online",
  statusTone: "primary",
  used: 89,
  total: 120,
  ratio: 0.74,
};

/* ── Profile banner (design §84-112) ──────────────────────────────────── */

export interface ProfileBannerData {
  name: string;
  roleTag: string;
  email: string;
  emailVerifiedTag: string;
  primaryAction: { label: string; icon: string };
  secondaryAction: { label: string; icon: string };
}

export const profileBanner: ProfileBannerData = {
  name: "Thomas Lin",
  roleTag: "首席研究员 (Admin)",
  email: "t.lin@argus-research.ai",
  emailVerifiedTag: "已验证企业域",
  primaryAction: { label: "管理资料", icon: "id_card" },
  secondaryAction: { label: "同步 SSO 凭据", icon: "sync" },
};

/* ── Long-term memory section (design §113-252) ───────────────────────── */

export interface MemoryRule {
  id: string;
  tag: string;
  tagTone: "primary" | "secondary" | "surface";
  body: string;
  weightLabel: string;
  scopeLabel: string;
  enabled: boolean;
}

export const memoryRulesSeed: readonly MemoryRule[] = [
  {
    id: "rule-preference",
    tag: "偏好规则",
    tagTone: "primary",
    body:
      "优先输出中文高密度研报，专业术语（如 HBM3e, NVLink, TCO, PUE）保留英文原文并附带规格演进注释。",
    weightLabel: "权重: 1.0 (强制)",
    scopeLabel: "作用域: 全部宏观与个股报告",
    enabled: true,
  },
  {
    id: "rule-citation",
    tag: "引用准则",
    tagTone: "secondary",
    body:
      "所有数据指标必须强制追溯至权威官方白皮书或学术评测数据集，杜绝无事实支撑的定性描述。",
    weightLabel: "权重: 0.95",
    scopeLabel: "验证层级: L1 白名单来源",
    enabled: true,
  },
  {
    id: "rule-focus",
    tag: "关注焦点",
    tagTone: "surface",
    body:
      "重点聚焦 AI 基础设施硬件、前沿大模型微架构推理吞吐优化及企业落地合规风险。",
    weightLabel: "权重: 0.88",
    scopeLabel: "自动触发专题关联推荐",
    enabled: true,
  },
] as const;

/* ── Active memory items section (design §253-424) ────────────────────── */

export type MemoryItemKind = "reflection" | "preference" | "definition" | "correction";

export interface MemoryItem {
  id: string;
  memId: string;
  kind: MemoryItemKind;
  body: string;
  recordedAt: string;
  relatedReports?: number;
  similarityThreshold?: number;
  scopeLabel?: string;
  highPriority?: boolean;
  sourceLabel?: string;
}

export const memoryItemsSeed: readonly MemoryItem[] = [
  {
    id: "mem-1",
    memId: "mem_8f902a",
    kind: "reflection",
    body:
      "GB200 NVL72 单机架峰值功耗为 120kW，不可直接在标准 15kW 风冷机房部署，分析此类架构必须包含二次液冷改造 TCO 评估。",
    recordedAt: "2026-09-15",
    relatedReports: 3,
    similarityThreshold: 0.84,
  },
  {
    id: "mem-2",
    memId: "mem_47c21e",
    kind: "preference",
    body:
      "对比硬件架构时优先采用三栏横向矩阵（如 H100 vs B200 vs MI300X），并突出 FP4 与 FP8 的吞吐差值。",
    recordedAt: "2026-09-12",
    relatedReports: 8,
    highPriority: true,
  },
  {
    id: "mem-3",
    memId: "mem_9011d8",
    kind: "definition",
    body:
      "将 Llama-3-70B 的长上下文评估基准严格界定在 32k-128k context window，默认 batch size 取 128。",
    recordedAt: "2026-09-08",
    scopeLabel: "上下文窗口校验规则",
  },
  {
    id: "mem-4",
    memId: "mem_3310cb",
    kind: "correction",
    body:
      "修正：AWS Trainium2 相比 H100 的能效比测算需剔除专有网络光模块折旧，更新折旧摊销模型至 3 年。",
    recordedAt: "2026-09-01",
    sourceLabel: "来自第 14 期研报推导复盘修正",
  },
] as const;

/** Filter tab counts (design §270-285). */
export interface MemoryFilter {
  id: "all" | "preference" | "reflection" | "definition" | "correction";
  label: string;
}

export const memoryFilters: readonly MemoryFilter[] = [
  { id: "all", label: "全部" },
  { id: "preference", label: "偏好规则" },
  { id: "reflection", label: "事实反思" },
  { id: "definition", label: "术语定义" },
  { id: "correction", label: "历史修正" },
] as const;

/* ── Provider status section (design §425-495) ───────────────────────── */

export type ProviderStatusKind = "connected" | "private" | "running";

export interface ProviderStatus {
  id: string;
  name: string;
  statusKind: ProviderStatusKind;
  statusLabel: string;
  metricLabel: string;
  metricTone?: "primary";
  ping?: boolean;
}

export const providerStatusesSeed: readonly ProviderStatus[] = [
  {
    id: "provider-claude",
    name: "Claude 3.5 Sonnet",
    statusKind: "connected",
    statusLabel: "已连接",
    metricLabel: "180ms",
    metricTone: "primary",
    ping: true,
  },
  {
    id: "provider-gpt4o",
    name: "GPT-4o",
    statusKind: "connected",
    statusLabel: "已连接",
    metricLabel: "240ms",
  },
  {
    id: "provider-deepseek",
    name: "DeepSeek-V3 / R1",
    statusKind: "private",
    statusLabel: "本地私有化",
    metricLabel: "42ms",
    metricTone: "primary",
    ping: true,
  },
  {
    id: "provider-voyage",
    name: "Voyage-AI Embed",
    statusKind: "running",
    statusLabel: "运行中",
    metricLabel: "voyage-3-large",
  },
] as const;
