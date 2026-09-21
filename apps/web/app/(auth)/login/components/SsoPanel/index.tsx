"use client";

import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import styles from "./index.module.css";

/**
 * SAML 2.0 / Okta / Azure AD collapsible portal entry.
 * Owns its own open/close state (UI-only).
 */
export function SsoPanel() {
  const [open, setOpen] = React.useState(false);
  return (
    <div className={styles.root}>
      <button
        id="sso-toggle"
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls="sso-panel"
        className={`${styles.toggle} group`}
      >
        <div className={styles.toggleLeft}>
          <IconSpan
            name="domain"
            size={16}
            className={`${styles.toggleIcon} text-outline group-hover:text-primary-container`}
          />
          <span className={styles.toggleText}>使用 SAML 2.0 / Okta / Azure AD 专属企业通道</span>
        </div>
        <IconSpan
          name="expand_more"
          size={16}
          className={`${styles.toggleArrow} ${open ? styles.toggleArrowOpen : ""}`}
        />
      </button>

      <div id="sso-panel" className={`${styles.panel} ${open ? "" : styles.panelHidden}`}>
        <div className={styles.panelHeader}>
          <label className={`${styles.panelLabel} font-label-sm`}>
            企业专属接入域名 (SSO Subdomain)
          </label>
          <span className={`${styles.panelBadge} font-label-sm font-mono`}>SAML 2.0 Ready</span>
        </div>
        <div className={styles.row}>
          <div className={styles.inputWrap}>
            <input
              type="text"
              placeholder="acme-corp"
              className={`${styles.input} font-code`}
            />
            <span className={`${styles.suffix} font-code`}>.argus.internal</span>
          </div>
          <button type="button" className={`${styles.jumpBtn} font-body-sm`}>
            <span>跳转认证</span>
            <IconSpan name="open_in_new" size={13} />
          </button>
        </div>
      </div>
    </div>
  );
}