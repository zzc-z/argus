import * as React from 'react'
import styles from './index.module.css'

/**
 * Bottom testimonial block — customer quote + avatar + copyright row.
 */
export function Testimonial() {
  return (
    <div className={styles.root}>
      <blockquote className={styles.quote}>
        「Argus 让我们的架构师团队从数千篇 SEC 报告与 ArXiv
        论文中自动化提炼关键决策点，原本需要两周的研报周期缩短到了两个小时，研究效率提升了 10
        倍以上。」
      </blockquote>
      <div className={styles.meta}>
        <div className={styles.author}>
          <div className={styles.avatar}>L</div>
          <div>
            <div className={styles.authorName}>某头部半导体实验室首席架构师</div>
            <div className={`${styles.authorRole} font-code`}>
              Silicon Core Lab · Global Research
            </div>
          </div>
        </div>
        <div className={`${styles.copyright} font-code`}>© 2026 Argus Systems Inc.</div>
      </div>
    </div>
  )
}
