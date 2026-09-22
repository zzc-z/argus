/**
 * Dashboard page — body only. Sidebar + TopBar are owned by
 * (dashboard)/layout.tsx, so this page renders only the inner content:
 *   <PageHeader /> + 4×KpiCard + RecentActivity | Subscriptions + ExploreGrid
 *
 * Composition data lives in ./mock.ts; components own their own styling.
 */

import { PageHeader } from "./components/PageHeader";
import { KpiCard } from "./components/KpiCard";
import { RecentActivity } from "./components/RecentActivity";
import { Subscriptions } from "./components/Subscriptions";
import { ExploreGrid } from "./components/ExploreGrid";
import { KPIS, ACTIVITIES, SUBSCRIPTIONS, REPORTS } from "./mock";
import styles from "./page.module.css";

export default function DashboardPage() {
  return (
    <div className={styles.content}>
      <PageHeader
        title="研究看板 (Research Dashboard)"
        titleChip="DAG Cluster v2.4"
        greeting="早上好，Tony"
        date="2026年9月19日 · 星期六"
        statusLabel="推理拓扑已就绪"
        notifications={3}
      />
      <section className={styles.kpiRow}>
        {KPIS.map((k) => (
          <KpiCard key={k.id} kpi={k} />
        ))}
      </section>
      <section className={styles.dualRow}>
        <RecentActivity items={ACTIVITIES} />
        <Subscriptions items={SUBSCRIPTIONS} />
      </section>
      <ExploreGrid reports={REPORTS} />
    </div>
  );
}
