'use client'

import * as React from 'react'
import { ArgusMark } from '@/components/common/ArgusMark'
import { IconSpan } from '@/components/common/IconSpan'
import { ThemeToggle } from '@/components/common/ThemeToggle'
import styles from './index.module.css'

/**
 * Login page top header — left: brand + version chip; right: docs + language.
 * 1:1 extracted from argus_3/code.html.
 */
export function LoginHeader() {
  return (
    <header className={styles.header}>
      <div className={styles.brand}>
        <ArgusMark size={20} />
        <div className={styles.brandText}>
          <span
            className={`${styles.brandName} font-headline-md font-semibold tracking-tight`}
          >
            Argus
          </span>
          <span className={`${styles.versionChip} font-label-sm font-medium tracking-tight`}>
            v2.4 Tech Preview
          </span>
        </div>
      </div>

      <nav className={styles.utility}>
        <a className={`${styles.utilityLink} hidden text-xs font-medium sm:flex`} href="#">
          <IconSpan name="help" size={15} className="text-outline" />
          <span>文档中心</span>
        </a>
        <span className={`${styles.utilitySep} font-code hidden text-xs sm:inline`}>/</span>
        <button type="button" className={`${styles.langBtn} text-xs`}>
          <IconSpan name="translate" size={14} />
          <span>简中</span>
        </button>
        <span className={`${styles.utilitySep} font-code hidden text-xs sm:inline`}>/</span>
        <ThemeToggle />
      </nav>
    </header>
  )
}
