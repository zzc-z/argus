import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import styles from "./index.module.less";

/**
 * Streaming synthesis terminal view inside the DAG card.
 * Two static agent messages + an animated caret.
 */
export function LiveTerminal() {
  return (
    <div className={`${styles.terminal} font-code`}>
      <div className={styles.head}>
        <span className={styles.headLeft}>
          <IconSpan name="terminal" size={13} className="text-purple-400" />
          <span>live-stream // report_gen_task_892b.md</span>
        </span>
        <span className={styles.live}>● 实时写入中</span>
      </div>
      <p className={styles.line}>
        <span className={styles.agentTag}>» [Agent-02]:</span>{" "}
        经对比 12 家主流 Foundry 财报与 IEEE 最新微架构测试基准，3nm GAA 漏电抑制指标已收敛。
      </p>
      <p className={styles.line}>
        <span className={styles.systemTag}>» [System]:</span>{" "}
        自动生成架构演进决策雷达图，预计 2.4s 后完成研报终审...
        <span className={styles.caret} />
      </p>
    </div>
  );
}