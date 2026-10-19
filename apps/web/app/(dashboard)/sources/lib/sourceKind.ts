/**
 * 资料类型 → 展示标签与图标。**sources 页与 add-sources 页共用这一份。**
 *
 * ## 为什么提取出来
 *
 * 之前两个页面各有一份 `Record`：
 * - `sources/lib/sourceTypes.ts` 的 `KIND_LABEL` / `ICON_NAME`
 * - `add-sources/lib/queueTypes.ts` 的 `KIND`
 *
 * 两份各自都是 `Record<ApiSourceType, ...>`，后端加一个 `SourceType`
 * 时 TS 会同时在两处报错（这部分是好的），但**改了措辞不会**——
 * 实测 docx 在资料库显示「DOCX」、在添加页队列显示「Word」，同一份资料
 * 两页两种叫法，没有任何提示。
 *
 * ## 标签为什么两页不同
 *
 * 不是笔误，是两页的设计语境不同：
 * - 资料库表格是紧凑的分类列 → 英文短词 `PDF` / `URL` / `Text` / `DOCX`
 * - 上传队列是给用户看的进度说明 → 带上下文的说法 `PDF` / `Web HTML` /
 *   `文稿` / `Word`
 *
 * 所以这里存**两份标签**（`libraryLabel` / `queueLabel`）而不是强行统一，
 * 但它们放在同一个文件、同一个类型下——改 docx 时会同时看到两个值，
 * 想要一致时一眼就能发现。
 */

import type { SourceTypeV } from '@/lib/api/sources'

export interface KindLabel {
  /** 资料库表格的类型列。 */
  libraryLabel: string
  /** 上传队列行的类型标签。 */
  queueLabel: string
  /** Material Symbol 名，两页共用（图标没有语境差异）。 */
  icon: string
}

export const KIND_LABELS: Record<SourceTypeV, KindLabel> = {
  pdf: { libraryLabel: 'PDF', queueLabel: 'PDF', icon: 'picture_as_pdf' },
  html: { libraryLabel: 'URL', queueLabel: 'Web HTML', icon: 'language' },
  text: { libraryLabel: 'Text', queueLabel: '文稿', icon: 'article' },
  docx: { libraryLabel: 'DOCX', queueLabel: 'Word', icon: 'article' },
}

/** 资料库表格用的类型标签。 */
export function mapLibraryLabel(type: SourceTypeV): string {
  return KIND_LABELS[type].libraryLabel
}

/** Material Symbol 名。两页共用。 */
export function mapIcon(type: SourceTypeV): string {
  return KIND_LABELS[type].icon
}
