/**
 * Dashboard page — body only. Sidebar + TopBar are owned by
 * (dashboard)/layout.tsx, so this page renders only the inner content
 * (1:1 with argus_dashboard/code.html).
 *
 * Composition:
 *   1. PageHeader      — title + chip + greeting + 3 right actions
 *   2. KPI grid (4)    — each card: uppercase label + value + sub + footer
 *   3. Dual panel      — RecentActivity (7 cols) | Subscriptions (5 cols)
 *   4. Explore grid    — 3 report cards with cover image + CTA
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
    <>
      <PageHeader
        title="研究看板 (Research Dashboard)"
        titleChip="DAG Cluster v2.4"
        greeting="早上好，Tony"
        date="2026年9月19日 · 星期六"
        notifications={3}
        activeSubscriptions={SUBSCRIPTIONS.filter((s) => !s.paused).length}
      />

      <section className={styles.kpiGrid}>
        {KPIS.map((k) => (
          <KpiCard key={k.id} kpi={k} />
        ))}
      </section>

      <section className={styles.dualGrid}>
        <RecentActivity items={ACTIVITIES} />
        <Subscriptions items={SUBSCRIPTIONS} />
      </section>

      <ExploreGrid reports={REPORTS} />
    </>
  );
}