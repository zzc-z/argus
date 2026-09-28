/** 5 个 semantic tone —— 业务侧只声明 tone，颜色映射统一在公共侧。
 *  设计稿中所有"状态相关"的色都收敛到这里；新增 tone 时只动这个文件 + 原语内部映射。 */
export type Tone = 'processing' | 'live' | 'ready' | 'failed' | 'idle'

/** tone → CSS class（挂在 .module.css 的 class 上；具体值在原语内用 cn 拼接） */
export const TONE: Record<Tone, {
  badgeBg: string
  badgeText: string
  dot: string
  iconTileBg: string
  iconTileText: string
}> = {
  processing: {
    badgeBg: 'toneProcessingBadgeBg',
    badgeText: 'toneProcessingBadgeText',
    dot: 'toneProcessingDot',
    iconTileBg: 'toneProcessingTileBg',
    iconTileText: 'toneProcessingTileText',
  },
  live: {
    badgeBg: 'toneLiveBadgeBg',
    badgeText: 'toneLiveBadgeText',
    dot: 'toneLiveDot',
    iconTileBg: 'toneLiveTileBg',
    iconTileText: 'toneLiveTileText',
  },
  ready: {
    badgeBg: 'toneReadyBadgeBg',
    badgeText: 'toneReadyBadgeText',
    dot: 'toneReadyDot',
    iconTileBg: 'toneReadyTileBg',
    iconTileText: 'toneReadyTileText',
  },
  failed: {
    badgeBg: 'toneFailedBadgeBg',
    badgeText: 'toneFailedBadgeText',
    dot: 'toneFailedDot',
    iconTileBg: 'toneFailedTileBg',
    iconTileText: 'toneFailedTileText',
  },
  idle: {
    badgeBg: 'toneIdleBadgeBg',
    badgeText: 'toneIdleBadgeText',
    dot: 'toneIdleDot',
    iconTileBg: 'toneIdleTileBg',
    iconTileText: 'toneIdleTileText',
  },
}