/**
 * Mock telemetry payload for the 404/500 error page.
 * Mirrors the inline JSON shown in argus_error_404_500/code.html.
 */
export interface TelemetrySnapshot {
  readonly status: number;
  readonly errorCode: string;
  readonly clusterRegion: string;
  readonly targetUri: string;
  readonly activeAgents: ReadonlyArray<{
    readonly name: string;
    readonly state: "running" | "terminated";
    readonly note?: string;
  }>;
  readonly dagCheckpoint: string;
  readonly memoryBuffer: {
    readonly vectorContextLength: number;
    readonly cachedNodes: number;
    readonly orphanTokens: number;
  };
  readonly suggestion: string;
  readonly epoch: number;
  readonly summary: {
    readonly latencyMs: number;
    readonly clusterHealthPct: number;
    readonly dataStateNote: string;
  };
}

export const telemetrySnapshot: TelemetrySnapshot = {
  status: 404,
  errorCode: "TOPOLOGY_NODE_NOT_FOUND",
  clusterRegion: "us-west-03.core.argus.internal",
  targetUri: "/reports/sess_quantum_arch_2026",
  activeAgents: [
    { name: "Supervisor_Lead", state: "running" },
    { name: "Researcher_v4", state: "running" },
    { name: "Critic_Evaluator", state: "terminated", note: "SIGTIMEOUT" },
  ],
  dagCheckpoint: "node_eval_critic:timeout_after_30s",
  memoryBuffer: {
    vectorContextLength: 128490,
    cachedNodes: 13,
    orphanTokens: 2410,
  },
  suggestion:
    "Verify session ID, reload topic subscription, or request agent failover.",
  epoch: 1740307200421,
  summary: {
    latencyMs: 42,
    clusterHealthPct: 99.98,
    dataStateNote: "本地草稿已同步至分布式容灾缓存",
  },
};

export const traceId = "argus_err_404_8f9a2e3b";
export const clusterNode = "cluster-us-west-03";
export const reportTitle = "研报拓扑节点未找到，或智能体正在紧急重调度";
export const reportSubtitle =
  "您所寻找的研究会话可能已迁移、被管理员归档，或者多智能体 DAG 执行链路遇到了瞬态异常。Argus 巡检探针正在自动尝试快照回滚与重平衡。";
