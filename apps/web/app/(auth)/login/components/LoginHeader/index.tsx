"use client";

import * as React from "react";
import { ArgusMark } from "@/components/common/ArgusMark";
import { IconSpan } from "@/components/common/IconSpan";
import styles from "./index.module.less";

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
          <span className={`${styles.brandName} font-headline-md font-semibold tracking-tight text-on-surface`}>
            Argus
          </span>
          <span className={`${styles.versionChip} font-label-sm font-medium tracking-tight`}>
            v2.4 Tech Preview
          </span>
        </div>
      </div>

      <nav className={styles.utility}>
        <a className={`${styles.utilityLink} hidden sm:flex text-xs font-medium`} href="#">
          <IconSpan name="help" size={15} className="text-outline" />
          <span>文档中心</span>
        </a>
        <span className={`${styles.utilitySep} hidden sm:inline font-code text-xs`}>/</span>
        <button type="button" className={`${styles.langBtn} text-xs`}>
          <IconSpan name="translate" size={14} />
          <span>简中</span>
        </button>
      </nav>
    </header>
  );
}