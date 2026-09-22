import * as React from "react";
import { ArgusMark } from "@/components/common/ArgusMark";
import { IconSpan } from "@/components/common/IconSpan";
import { StatusDot } from "@/components/common/StatusDot";
import styles from "./index.module.css";

interface NavItem {
  id: string;
  icon: string;
  label: string;
  active: boolean;
  badge?: string;
}

const NAV: NavItem[] = [
  { id: "dashboard", icon: "analytics", label: "看板", active: true },
  { id: "research", icon: "biotech", label: "深度研报", active: false },
  { id: "intel", icon: "radar", label: "实时情报", active: false, badge: "12" },
  { id: "sources", icon: "dataset", label: "数据源", active: false },
  { id: "agents", icon: "deployed_code", label: "智能体实验室", active: false },
  { id: "audit", icon: "fact_check", label: "审计与导出", active: false },
];

/** Fixed left navigation column. 1:1 extracted from argus_dashboard/code.html sidebar. */
export function Sidebar() {
  return (
    <aside className={styles.root}>
      <div className={styles.brand}>
        <ArgusMark size={22} className="text-primary-container" />
        <div className={styles.brandText}>
          <span className={`${styles.brandName} font-headline-md font-semibold tracking-tight`}>
            Argus
          </span>
          <span className={`${styles.brandSub} font-label-sm`}>Research OS</span>
        </div>
      </div>

      <nav className={styles.nav}>
        <p className={`${styles.navLabel} font-label-sm uppercase tracking-wider`}>研究工作台</p>
        <ul className={styles.navList}>
          {NAV.map((n) => (
            <li key={n.id}>
              <a
                href="#"
                className={`${styles.navItem} ${n.active ? styles.navItemActive : ""}`}
              >
                <IconSpan
                  name={n.icon}
                  size={18}
                  className={n.active ? "text-primary-container" : "text-secondary"}
                />
                <span className={`${styles.navLabel2} ${n.active ? styles.navLabelActive : ""}`}>
                  {n.label}
                </span>
                {n.badge && <span className={styles.navBadge}>{n.badge}</span>}
              </a>
            </li>
          ))}
        </ul>
      </nav>

      <div className={styles.footer}>
        <div className={styles.footerStatus}>
          <StatusDot color="emerald" ping />
          <div className={styles.footerStatusText}>
            <p className={`${styles.footerStatusTitle} font-label-sm font-medium`}>全部系统运行</p>
            <p className={`${styles.footerStatusMeta} font-label-sm`}>6 个节点 · 12.4 GB / 256 GB</p>
          </div>
        </div>
        <button type="button" className={`${styles.footerBtn} font-label-sm`}>
          <IconSpan name="settings" size={14} />
          <span>系统设置</span>
        </button>
      </div>
    </aside>
  );
}