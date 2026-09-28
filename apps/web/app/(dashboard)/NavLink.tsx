'use client'

import * as React from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'

import { IconSpan } from '@/components/common/IconSpan'

import styles from './layout.module.css'

// Routes that should highlight the "报告列表" nav item, even when the current
// path is the report-detail page (`/report`). Keeps the sidebar in sync with
// the user mental model: 报告列表 is the parent group.
const REPORTS_PARENT_ALIASES = ['/reports', '/report'] as const

function isReportsActive(pathname: string): boolean {
  return REPORTS_PARENT_ALIASES.some(
    (p) => pathname === p || pathname.startsWith(p + '/'),
  )
}

function isNavItemActive(pathname: string, href: string): boolean {
  // Report detail belongs to the 报告列表 group.
  if (href === '/reports' && isReportsActive(pathname)) return true
  return pathname === href || pathname.startsWith(href + '/')
}

interface NavLinkProps {
  href: string
  icon: string
  label: string
}

export function NavLink({ href, icon, label }: NavLinkProps) {
  const pathname = usePathname()
  const active = isNavItemActive(pathname, href)
  const className = `${styles.navLink} ${active ? styles.navLinkActive : ''}`
  return (
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    <Link href={href as any} className={className} aria-current={active ? 'page' : undefined}>
      <IconSpan name={icon} size={18} />
      <span className="font-body-sm">{label}</span>
    </Link>
  )
}
