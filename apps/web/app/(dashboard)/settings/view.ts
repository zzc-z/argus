/**
 * 设置页的视图常量与数据映射。
 *
 * 原本这里是一整份 `mock.ts`（假供应商、假向量索引进度、假用户资料）。
 * 假数据已删——现在这些值都来自后端：
 *   - 供应商配置状态、向量索引规模 → `GET /api/v1/settings/status`
 *   - 当前用户资料 → `GET /api/v1/me`（由全局 UserContext 拉取，见 `lib/auth`）
 *
 * 剩下的常量只有两类：左侧导航项的静态文案，以及「后端字段 → 组件形状」
 * 的映射函数。映射放在这里而不是组件里，组件就只管渲染。
 *
 * Lives next to the route (per project convention).
 */

import type { ProviderStatusV, VectorIndexV } from '@/lib/api/settings'
import type { CurrentUser } from '@/lib/auth'

/* ── 左侧导航 ────────────────────────────────────────────────────────── */

export type SettingsNavId = 'profile' | 'api-keys' | 'prompts' | 'tools' | 'quota' | 'danger'

export interface SettingsNavItem {
  id: SettingsNavId
  label: string
  hint: string
  icon: string
  danger?: boolean
}

/**
 * 「记忆与偏好」条目已删：它指向的长期记忆规则区与记忆条目区没有后端
 * 数据源（后端无 memory_rules 表），整块删掉了。
 */
export const settingsNavItems: readonly SettingsNavItem[] = [
  { id: 'profile', label: '个人资料', hint: 'Profile', icon: 'badge' },
  { id: 'api-keys', label: '模型与 API 密钥', hint: 'Keys', icon: 'key' },
  { id: 'prompts', label: '智能体提示词模版', hint: 'Prompts', icon: 'terminal' },
  { id: 'tools', label: '第三方工具集成', hint: 'Tools', icon: 'hub' },
  { id: 'quota', label: '订阅与算力配额', hint: 'Quota', icon: 'credit_card' },
  { id: 'danger', label: '安全与危险区域', hint: 'Danger', icon: 'warning', danger: true },
] as const

/* ── 供应商状态 ──────────────────────────────────────────────────────── */

export interface ProviderStatus {
  id: string
  name: string
  /** 配置是否就绪。后端 `configured`。 */
  configured: boolean
  /** 状态词，如 '已配置' / '未配置'。 */
  statusLabel: string
  /** 补充信息：缺失的密钥名、中转站地址等。 */
  metricLabel: string
  /** 状态点是否带脉冲动画——只给已配置的供应商。 */
  ping: boolean
}

/**
 * 后端 `ProviderStatusV` → 组件消费的形状。
 *
 * `detail` 是后端写给人看的一句话，形如 '已配置' /
 * '未配置 TAVILY_API_KEY' / '已配置（经中转站 https://llmapi.pro）'。
 * 卡片左侧已经有状态词了，所以这里把 detail 开头的状态词去掉，只留
 * 补充信息（'TAVILY_API_KEY' / '经中转站 https://llmapi.pro'）；
 * 去掉后为空（detail 就是 '已配置'）就退回显示能力 id。
 */
export function toProviderStatus(p: ProviderStatusV): ProviderStatus {
  const statusLabel = p.configured ? '已配置' : '未配置'
  const rest = p.detail.startsWith(statusLabel) ? p.detail.slice(statusLabel.length) : p.detail
  const metricLabel = rest.replace(/^[（(]\s*/, '').replace(/\s*[）)]$/, '').trim()
  return {
    id: p.id,
    name: p.name,
    configured: p.configured,
    statusLabel,
    metricLabel: metricLabel.length > 0 ? metricLabel : p.id,
    ping: p.configured,
  }
}

/* ── 向量索引诊断 ────────────────────────────────────────────────────── */

export interface VectorIndexDiagnostic {
  label: string
  statusLabel: string
  /** 已向量化的切片数。 */
  used: number
  /** 切片总数。 */
  total: number
  /** 已向量化的比例，0..1。 */
  ratio: number
}

/**
 * 后端 `VectorIndexV` → 侧栏诊断卡。
 *
 * 比例 = 已嵌入切片 / 切片总数。后端的 `embedded_chunk_count` 统计的是
 * **整个向量库**的向量数（向量表没有 user_id 列），而 `chunk_count` 是
 * 当前用户的——多用户部署下比例可能大于 1，所以条形图宽度封顶在 100%。
 */
export function toVectorIndexDiagnostic(v: VectorIndexV): VectorIndexDiagnostic {
  const total = v.chunk_count
  const used = v.embedded_chunk_count
  const ratio = total > 0 ? used / total : 0
  return {
    label: '向量索引状态',
    statusLabel: describeVectorIndex(total, used, ratio),
    used,
    total,
    ratio,
  }
}

/** 索引健康度的一句话描述。比例越高说明越接近「都嵌好了」。 */
function describeVectorIndex(total: number, used: number, ratio: number): string {
  if (total === 0) return '暂无资料'
  if (ratio >= 1) return '已就绪'
  if (used === 0) return '未开始'
  return '正在构建'
}

/* ── 个人资料横幅 ────────────────────────────────────────────────────── */

export interface ProfileBannerData {
  name: string
  roleTag: string
  email: string
  emailVerifiedTag: string
  primaryAction: { label: string; icon: string }
  secondaryAction: { label: string; icon: string }
}

/**
 * 当前用户 → 横幅内容。
 *
 * `/api/v1/me` 只有 id / email / display_name / avatar_url 四个字段：
 * 没有角色，也没有「邮箱是否已验证」的标记。所以：
 *   - 角色标签是**静态产品标签**（这个产品就是给研究员用的），不是用户角色。
 *   - 验证标签只能反映「邮箱有没有绑上」——后端没给验证状态，不能瞎写
 *     「已验证」。
 */
export function toProfileBanner(user: CurrentUser | null): ProfileBannerData {
  const displayName = user?.display_name?.trim() ?? ''
  const email = user?.email?.trim() ?? ''
  return {
    name: displayName.length > 0 ? displayName : email.length > 0 ? email : '未命名用户',
    roleTag: '研究员',
    email: email.length > 0 ? email : '未绑定邮箱',
    emailVerifiedTag: email.length > 0 ? '邮箱已绑定' : '邮箱未绑定',
    primaryAction: { label: '管理资料', icon: 'id_card' },
    secondaryAction: { label: '同步 SSO 凭据', icon: 'sync' },
  }
}
