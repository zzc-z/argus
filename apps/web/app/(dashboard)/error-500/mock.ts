/**
 * Mock telemetry payload for the /error-500 page.
 * Mirrors the structure exported from ../error-404/mock.ts but specialized
 * for a 5xx server-fault narrative.
 */
import type { TelemetrySnapshot } from '../error-404/mock'

export const telemetrySnapshot: TelemetrySnapshot = {
  status: 500,
  errorCode: 'DAG_RUNTIME_INVARIANT_BROKEN',
  clusterRegion: 'us-west-03.core.argus.internal',
  targetUri: '/reports/sess_quantum_arch_2026/run_882/phase_synthesize',
  activeAgents: [
    { name: 'Supervisor_Lead', state: 'running' },
    { name: 'Synthesizer_v3', state: 'terminated', note: 'SIGABRT: invariant_violation' },
    { name: 'Critic_Evaluator', state: 'terminated', note: 'SIGSEGV: upstream_5xx_propagated' },
  ],
  dagCheckpoint: 'node_synth_invoke:cold_cache_miss_after_30s',
  memoryBuffer: {
    vectorContextLength: 142117,
    cachedNodes: 9,
    orphanTokens: 4102,
  },
  suggestion:
    'Trigger failover, replay last committed DAG checkpoint, or escalate to on-call SRE.',
  epoch: 1740307245511,
  summary: {
    latencyMs: 1284,
    clusterHealthPct: 96.42,
    dataStateNote: '本地草稿已冻结，等待巡检确认',
  },
}

export const traceId = 'argus_err_500_9c1f4a72'
export const clusterNode = 'cluster-us-west-03'