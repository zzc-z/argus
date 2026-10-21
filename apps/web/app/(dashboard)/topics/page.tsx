'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'

import { PageLayout } from '@/components/common/PageLayout'
import { EmptyState } from '@/components/common/EmptyState'
import { IconSpan } from '@/components/common/IconSpan'

import styles from './page.module.css'

/**
 * /topics — 主题订阅（Topic Subscriptions）。
 *
 * ## 为什么这个页面只有空态
 *
 * 后端没有「主题 / 订阅」这个概念：数据库里只有 users / accounts /
 * sources / document_chunks / reports / report_sources 六张表
 * （见 apps/api/app/models/），既没有 topics 表，也没有创建 / 更新 /
 * 暂停订阅的接口。
 *
 * 因此本页**不展示任何列表、指标或统计数字**——以前那些行是编出来的，
 * 点进去没有对应数据。现在这里诚实地说清「缺什么」和「现在能做什么」。
 *
 * 导航入口保留在侧边栏（layout.tsx 的 NavLink），等后端补齐模型与接口
 * 之后，这里直接换成真实数据即可。
 */

interface NextStep {
  /** Material Symbol 名。取自本仓库已在用的图标集合。 */
  icon: string
  title: string
  description: string
  href: '/explore' | '/sources' | '/reports'
}

/** 现在真正可用的替代路径——都指向已接通后端的页面。 */
const NEXT_STEPS: ReadonlyArray<NextStep> = [
  {
    icon: 'explore',
    title: '去 /explore 提问',
    description: '一次性把研究问题交给多智能体流水线，产出带引用的报告。',
    href: '/explore',
  },
  {
    icon: 'cloud_upload',
    title: '去 /sources 上传资料',
    description: '上传 PDF / 网页 / 文本并建立索引，让检索有据可依。',
    href: '/sources',
  },
  {
    icon: 'dynamic_feed',
    title: '去 /reports 看产出',
    description: '已生成的研究报告都在报告库里，可按状态与时间筛选。',
    href: '/reports',
  },
]

function NextStepCard({ step }: { step: NextStep }) {
  return (
    <Link
      href={step.href}
      className="flex flex-col gap-1 rounded-lg border border-outline-variant bg-surface-container-low p-4 transition-colors hover:bg-surface-container"
    >
      <span className="flex items-center gap-2 text-on-surface">
        <IconSpan name={step.icon} size={18} className="text-secondary" />
        <span className="font-headline-sm text-headline-sm">{step.title}</span>
      </span>
      <span className="text-on-surface-variant font-body-sm text-body-sm">{step.description}</span>
    </Link>
  )
}

export default function TopicsPage() {
  const router = useRouter()

  return (
    <PageLayout
      header={{
        title: '主题订阅',
        enLabel: 'Topic Subscriptions',
        subtitle: '订阅能力尚未接入后端——本页只保留入口，不展示任何模拟数据。',
      }}
    >
      <EmptyState
        icon="rss_feed"
        title="主题订阅还没有后端支撑"
        description="后端目前既没有主题 / 订阅的数据模型，也没有创建、更新、暂停订阅的接口；数据库里只有 users、accounts、sources、document_chunks、reports、report_sources 六张表。所以这里显示不出任何真实的订阅——原先的订阅列表、指标磁贴、推荐模板和 Agent 日志都是编的，已经移除。"
        action={{ label: '去 /explore 提问', onClick: () => router.push('/explore') }}
      />

      <section className="mt-6 flex flex-col gap-3">
        <h2 className="text-on-surface font-headline-sm text-headline-sm">现在能做什么</h2>
        {/* 复用 topics 自己的 page.module.css 栅格——该文件不改动。 */}
        <div className={styles.recommendSection}>
          {NEXT_STEPS.map((step) => (
            <NextStepCard key={step.href} step={step} />
          ))}
        </div>
      </section>
    </PageLayout>
  )
}
