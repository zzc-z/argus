/**
 * 错误页的诊断快照。
 *
 * ## 原来这里是什么
 *
 * 原设计稿给 404/500 页配了一份「集群故障」快照：`clusterRegion:
 * "us-west-03"`、活跃智能体列表、向量上下文长度、孤儿 token 数、集群健康
 * 百分比……**后端一个字段都没有**，而且 404 是「路由没匹配上」，跟集群
 * 故障毫无关系——挂着这些只会让人以为出了生产事故，去查一个不存在的
 * 问题。
 *
 * ## 现在是什么
 *
 * 只放**这一页真的知道**的事实：状态码、请求的路径、浏览器 UA、发生时间、
 * 后端 liveness 探测结果、本次的 trace id。字段名也照着这些事实起，
 * 不再假装有集群。
 */
export interface TelemetrySnapshot {
  /** HTTP 状态码。404 / 500。 */
  readonly status: number
  /** 触发这次错误的目标地址。 */
  readonly targetUri: string
  /** 事件时间戳（毫秒）。 */
  readonly epoch: number
  /** 事件时间的可读形式。 */
  readonly occurredAt: string
  /** 请求路径。 */
  readonly path: string
  /** 浏览器 User-Agent。 */
  readonly userAgent: string
  /** 后端 liveness 探测结果——null 表示探测本身失败。 */
  readonly backendProbe: string | null
  /** 这次的 trace id。页面加载时生成，与下方 TraceIdBar 一致。 */
  readonly traceId: string
  /** 给用户的一句话建议。 */
  readonly suggestion: string
  /** 一句话摘要（给抽屉标题用）。 */
  readonly summary: string
}
