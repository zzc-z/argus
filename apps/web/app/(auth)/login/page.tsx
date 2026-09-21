"use client";

/**
 * Login page — mechanical 1:1 conversion of design/argus_3/code.html.
 * Source HTML kept at apps/web/design-argus-3.html for diff.
 *
 * Conversion rules (kept verbatim, no semantic restructuring):
 *   • class / for / tabindex → className / htmlFor / tabIndex
 *   • Inline <style> and tailwind <script> blocks from source are dropped
 *     (Tailwind v3 + tailwind.config.ts already supply the tokens).
 *   • Material Symbols Outlined stays as Google Fonts <link> in layout.tsx.
 *   • Source inline JS (⌘G/⌘W hotkeys + SSO toggle) → useEffect.
 *   • "use client" required because of onSubmit / useEffect / window.
 */

import { useEffect, useState } from "react";

export default function LoginPage() {
  const [ssoOpen, setSsoOpen] = useState(false);

  // Keyboard shortcuts: ⌘G / ⌘W (or G/W) → flash OAuth button.
  // Skipped when focus is inside an input/textarea (verbatim from source).
  useEffect(() => {
    const flash = (id: string) => {
      const btn = document.getElementById(id);
      if (!btn) return;
      btn.classList.add("ring-2", "ring-purple-400", "scale-[0.98]");
      window.setTimeout(() => {
        btn.classList.remove("ring-2", "ring-purple-400", "scale-[0.98]");
      }, 200);
    };

    const handler = (e: KeyboardEvent) => {
      const tag = (document.activeElement as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      if (e.key === "g" || e.key === "G") flash("btn-oauth-github");
      else if (e.key === "w" || e.key === "W") flash("btn-oauth-google");
    };

    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  return (
    <main className="min-h-full flex flex-col lg:flex-row w-full overflow-x-hidden">
      {/* LEFT COLUMN: Minimalist Precision Authentication Area (46%) */}
      <div className="w-full lg:w-[46%] xl:w-[44%] flex flex-col justify-between bg-surface-container-lowest border-r border-surface-container-high/70 relative z-10 px-6 sm:px-12 md:px-16 lg:px-14 xl:px-20 py-8 lg:py-10">
        {/* Top Header: Logo Brand & Language Switcher */}
        <header className="flex items-center justify-between w-full">
          <div className="flex items-center gap-3">
            {/* Argus Precise Vector Mark */}
            <div className="relative w-9 h-9 bg-primary-container/10 border border-primary-container/20 rounded-lg flex items-center justify-center shadow-xs">
              <svg
                className="w-5 h-5 text-primary-container"
                fill="none"
                viewBox="0 0 24 24"
                xmlns="http://www.w3.org/2000/svg"
              >
                <circle
                  className="opacity-30"
                  cx="12"
                  cy="12"
                  r="9"
                  stroke="currentColor"
                  strokeWidth="1.75"
                />
                <path
                  d="M12 3C7.02944 3 3 7.02944 3 12C3 16.9706 7.02944 21 12 21"
                  stroke="currentColor"
                  strokeLinecap="round"
                  strokeWidth="2"
                />
                <circle
                  cx="12"
                  cy="12"
                  fill="#ffffff"
                  r="4.25"
                  stroke="currentColor"
                  strokeWidth="1.75"
                />
                <circle cx="12" cy="12" fill="currentColor" r="2" />
                <path
                  className="opacity-50"
                  d="M12 7.75V3M21 12H16.25M12 21v-4.75M3 12h4.75"
                  stroke="currentColor"
                  strokeLinecap="round"
                  strokeWidth="1.5"
                />
              </svg>
            </div>
            <div className="flex items-center gap-2">
              <span className="font-headline-md font-semibold tracking-tight text-on-surface">
                Argus
              </span>
              <span className="font-label-sm text-[11px] text-primary-container bg-primary-fixed/70 border border-primary-fixed-dim px-2 py-0.5 rounded-full font-medium tracking-tight">
                v2.4 Tech Preview
              </span>
            </div>
          </div>
          {/* Quick Utility */}
          <div className="flex items-center gap-2 text-secondary text-sm">
            <a
              className="hidden sm:flex items-center gap-1 hover:text-on-surface transition-colors text-xs font-medium"
              href="#"
            >
              <span className="material-symbols-outlined text-[15px] text-outline" style={{ fontSize: "15px" }}>
                help
              </span>
              <span>文档中心</span>
            </a>
            <span className="hidden sm:inline text-outline-variant font-code text-xs">
              /
            </span>
            <button
              className="flex items-center gap-1 px-2 py-1 rounded hover:bg-surface-container-low text-xs text-on-surface-variant transition-colors border border-transparent hover:border-surface-container"
              type="button"
            >
              <span className="material-symbols-outlined text-[14px]" style={{ fontSize: "14px" }}>
                translate
              </span>
              <span>简中</span>
            </button>
          </div>
        </header>

        {/* Center Content: Primary Auth Form */}
        <div className="my-auto py-10 w-full max-w-[420px] mx-auto">
          {/* Welcome Typography */}
          <div className="mb-8">
            <h1 className="text-2xl sm:text-[28px] font-headline-lg font-semibold tracking-tight text-on-surface">
              登录您的研究工作台
            </h1>
            <p className="text-body-sm text-secondary mt-2 leading-relaxed">
              多智能体深度研报 · 面向工程师与研究员的 AI 洞察引擎
            </p>
          </div>

          {/* Quick OAuth Actions */}
          <div className="space-y-3">
            {/* GitHub Button */}
            <button
              className="group relative w-full flex items-center justify-between px-4 py-3 bg-[#16191f] hover:bg-[#0d1015] active:scale-[0.99] text-white rounded-lg transition-all duration-150 shadow-sm border border-neutral-800"
              id="btn-oauth-github"
              type="button"
            >
              <div className="flex items-center gap-3">
                <svg
                  className="w-5 h-5 fill-current transition-transform duration-200 group-hover:scale-105"
                  viewBox="0 0 24 24"
                >
                  <path
                    clipRule="evenodd"
                    d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"
                    fillRule="evenodd"
                  />
                </svg>
                <span className="text-sm font-medium tracking-tight">
                  使用 GitHub 账号继续
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                <kbd className="font-code text-[11px] text-neutral-400 bg-neutral-800/80 px-1.5 py-0.5 rounded border border-neutral-700">
                  ⌘G
                </kbd>
                <span className="material-symbols-outlined text-[16px] text-neutral-400 group-hover:translate-x-0.5 transition-transform" style={{ fontSize: "16px" }}>
                  arrow_forward
                </span>
              </div>
            </button>

            {/* Google Workspace Button */}
            <button
              className="group relative w-full flex items-center justify-between px-4 py-3 bg-surface-container-lowest hover:bg-surface-container-low active:scale-[0.99] text-on-surface rounded-lg transition-all duration-150 shadow-xs border border-surface-container-highest"
              id="btn-oauth-google"
              type="button"
            >
              <div className="flex items-center gap-3">
                <svg
                  className="w-5 h-5 flex-shrink-0"
                  viewBox="0 0 24 24"
                >
                  <path
                    d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
                    fill="#4285F4"
                  />
                  <path
                    d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                    fill="#34A853"
                  />
                  <path
                    d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"
                    fill="#FBBC05"
                  />
                  <path
                    d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"
                    fill="#EA4335"
                  />
                </svg>
                <span className="text-sm font-medium tracking-tight">
                  使用 Google Workspace 账号继续
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                <kbd className="font-code text-[11px] text-secondary bg-surface-container px-1.5 py-0.5 rounded border border-surface-container-high">
                  ⌘W
                </kbd>
                <span className="material-symbols-outlined text-[16px] text-secondary group-hover:translate-x-0.5 transition-transform" style={{ fontSize: "16px" }}>
                  arrow_forward
                </span>
              </div>
            </button>
          </div>

          {/* Elegant Linear Divider */}
          <div className="relative flex items-center justify-center my-6">
            <div className="w-full h-px bg-surface-container-high" />
            <span className="absolute px-3 bg-surface-container-lowest font-label-sm text-[11px] text-outline uppercase tracking-wider">
              或通过企业邮箱 / SSO
            </span>
          </div>

          {/* Magic Link / Work Email Direct Form */}
          <form
            className="space-y-3"
            onSubmit={(e) => e.preventDefault()}
          >
            <div>
              <label
                className="block font-label-sm text-[12px] text-on-surface-variant mb-1.5 font-medium"
                htmlFor="work-email"
              >
                工作邮箱地址
              </label>
              <div className="relative">
                <span className="material-symbols-outlined absolute left-3 top-2.5 text-outline text-[18px] pointer-events-none" style={{ fontSize: "18px", top: "13px" }}>
                  mail
                </span>
                <input
                  className="w-full bg-surface-container-low/60 hover:bg-surface-container-low focus:bg-white text-on-surface placeholder:text-outline/70 border border-surface-container-highest rounded-lg pl-9 pr-28 py-2.5 text-sm font-body-md transition-all focus:outline-none focus:ring-2 focus:ring-primary-container/20 focus:border-primary-container"
                  id="work-email"
                  placeholder="name@company.com"
                  type="email"
                />
                <button
                  className="absolute right-1.5 top-1.5 bottom-1.5 px-3 bg-primary-container hover:bg-primary text-white rounded-md text-xs font-medium transition-all flex items-center gap-1 shadow-xs hover:shadow"
                  type="submit"
                >
                  <span>发送免密链接</span>
                  <span className="material-symbols-outlined text-[14px]" style={{ fontSize: "14px" }}>
                    send
                  </span>
                </button>
              </div>
            </div>
          </form>

          {/* SAML 2.0 / Okta Dedicated Portal Expansion */}
          <div className="mt-4 pt-2">
            <button
              className="w-full py-2 px-3 rounded-lg border border-dashed border-outline-variant/70 hover:border-primary-container/50 bg-surface-container-low/40 hover:bg-primary-fixed/20 flex items-center justify-between text-xs text-secondary hover:text-primary-container transition-all group"
              id="sso-toggle"
              type="button"
              onClick={() => setSsoOpen((v) => !v)}
              aria-expanded={ssoOpen}
              aria-controls="sso-panel"
            >
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-[16px] text-outline group-hover:text-primary-container" style={{ fontSize: "16px" }}>
                  domain
                </span>
                <span className="font-medium">
                  使用 SAML 2.0 / Okta / Azure AD 专属企业通道
                </span>
              </div>
              <span
                className={`material-symbols-outlined text-[16px] transition-transform duration-200 ${
                  ssoOpen ? "rotate-180" : ""
                }`}
                style={{ fontSize: "16px" }}
              >
                expand_more
              </span>
            </button>

            {/* Collapsible SSO Form Container */}
            <div
              className={`mt-2.5 p-3.5 bg-surface-container-low/80 border border-surface-container-high rounded-lg space-y-2.5 ${
                ssoOpen ? "" : "hidden"
              }`}
              id="sso-panel"
            >
              <div className="flex items-center justify-between">
                <label className="font-label-sm text-[11px] text-secondary">
                  企业专属接入域名 (SSO Subdomain)
                </label>
                <span className="font-label-sm text-[10px] text-primary-container font-mono bg-primary-fixed px-1 rounded">
                  SAML 2.0 Ready
                </span>
              </div>
              <div className="flex gap-2">
                <div className="relative flex-1">
                  <input
                    className="w-full bg-surface-container-lowest px-3 py-2 font-code text-xs text-on-surface rounded-md border border-surface-container-high focus:border-primary-container focus:outline-none focus:ring-1 focus:ring-primary-container pr-24"
                    placeholder="acme-corp"
                    type="text"
                  />
                  <span className="absolute right-2.5 top-2.5 font-code text-[11px] text-outline pointer-events-none">
                    .argus.internal
                  </span>
                </div>
                <button
                  className="bg-on-surface hover:bg-black text-white px-3.5 py-2 rounded-md font-body-sm text-xs font-medium transition-colors flex items-center gap-1"
                  type="button"
                >
                  <span>跳转认证</span>
                  <span className="material-symbols-outlined text-[13px]" style={{ fontSize: "13px" }}>
                    open_in_new
                  </span>
                </button>
              </div>
            </div>
          </div>

          {/* Legal Policy & Terms */}
          <div className="mt-6 text-center">
            <p className="text-[12px] text-secondary leading-relaxed">
              继续操作即表示您已阅读并同意 Argus 的
              <a
                className="text-on-surface font-medium underline underline-offset-2 hover:text-primary-container transition-colors"
                href="#"
              >
                《服务条款》
              </a>
              与
              <a
                className="text-on-surface font-medium underline underline-offset-2 hover:text-primary-container transition-colors"
                href="#"
              >
                《隐私政策与数据隔离承诺》
              </a>
            </p>
          </div>
        </div>

        {/* Bottom Security Guarantees Micro-Badges */}
        <footer className="pt-4 border-t border-surface-container-high/60 flex flex-wrap items-center justify-between gap-y-2 text-secondary font-label-sm text-[11px]">
          <div className="flex items-center gap-1.5">
            <span className="material-symbols-outlined text-[15px] text-primary-container" style={{ fontSize: "15px" }}>
              verified_user
            </span>
            <span>端到端隔离环境</span>
          </div>
          <span className="text-outline-variant">/</span>
          <div className="flex items-center gap-1.5">
            <span className="material-symbols-outlined text-[15px] text-primary-container" style={{ fontSize: "15px" }}>
              bolt
            </span>
            <span>零保留模型训练</span>
          </div>
          <span className="text-outline-variant">/</span>
          <div className="flex items-center gap-1.5">
            <span className="material-symbols-outlined text-[15px] text-primary-container" style={{ fontSize: "15px" }}>
              security
            </span>
            <span>SOC2 Type II 审计中</span>
          </div>
        </footer>
      </div>

      {/* RIGHT COLUMN: Immersive Tech Visualization & Value Showcase (54%) */}
      <div className="w-full lg:w-[54%] xl:w-[56%] bg-[#0e1017] text-white flex flex-col justify-between p-8 sm:p-12 lg:p-16 relative overflow-hidden">
        {/* Atmospheric Ambient Glows & Tech Grid Background */}
        <div className="absolute inset-0 tech-grid-pattern opacity-30 pointer-events-none" />
        <div className="absolute top-1/4 right-10 w-[480px] h-[480px] bg-[#7039f9]/20 rounded-full blur-[120px] pointer-events-none" />
        <div className="absolute bottom-10 left-10 w-[380px] h-[380px] bg-[#3b198f]/25 rounded-full blur-[100px] pointer-events-none" />

        {/* Top Live System Telemetry Bar */}
        <div className="relative z-10 flex flex-wrap items-center justify-between gap-4">
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-white/5 border border-white/10 backdrop-blur-md">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
            </span>
            <span className="font-label-sm text-xs font-medium text-neutral-200">
              14 个分布式探针节点就绪
            </span>
            <span className="text-white/20">|</span>
            <span className="font-code text-xs text-neutral-400">
              99.98% 正常运行时间
            </span>
          </div>
          <div className="hidden sm:flex items-center gap-2 font-code text-xs text-neutral-400">
            <span className="text-neutral-500">Cluster:</span>
            <span className="text-purple-300">us-west-2</span>
            <span className="text-neutral-600">·</span>
            <span>8.2k tokens/s</span>
          </div>
        </div>

        {/* Centerpiece: Realistic DAG Topology & Realtime Research Agent UI */}
        <div className="relative z-10 my-8 max-w-[620px] mx-auto w-full">
          {/* Ambient Card Shell with Precision Border & Glass Effect */}
          <div className="relative rounded-2xl bg-[#141824]/90 border border-white/10 shadow-2xl backdrop-blur-xl p-5 sm:p-6 overflow-hidden">
            {/* Card Window Header */}
            <div className="flex items-center justify-between pb-4 border-b border-white/10">
              <div className="flex items-center gap-2">
                <div className="flex gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-full bg-rose-500/80" />
                  <span className="w-2.5 h-2.5 rounded-full bg-amber-500/80" />
                  <span className="w-2.5 h-2.5 rounded-full bg-emerald-500/80" />
                </div>
                <span className="ml-2 font-code text-xs text-neutral-300 font-medium">
                  pipeline: deep-research-dag // active
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-code bg-purple-500/20 text-purple-300 border border-purple-500/30">
                  5 智能体协作中
                </span>
                <span className="font-code text-[11px] text-neutral-400">
                  7ms 流式响应
                </span>
              </div>
            </div>

            {/* DAG Agent Nodes Topology Mockup */}
            <div className="pt-5 pb-3">
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                {/* Agent 1 */}
                <div className="p-3 rounded-lg bg-white/[0.03] border border-white/10 hover:border-purple-500/40 transition-colors">
                  <div className="flex items-center justify-between text-xs mb-1.5">
                    <span className="font-code text-[11px] text-purple-400 font-semibold">
                      01. 搜索探针
                    </span>
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                  </div>
                  <p className="text-xs text-neutral-200 font-medium truncate">
                    ArXiv + SEC 深度检索
                  </p>
                  <p className="font-code text-[10px] text-neutral-400 mt-1">
                    42 篇论文已解析
                  </p>
                </div>
                {/* Agent 2 */}
                <div className="p-3 rounded-lg bg-purple-900/20 border border-purple-500/40 relative shadow-inner">
                  <div className="absolute -top-2 right-2 px-1.5 py-0.2 bg-purple-600 rounded text-[9px] font-code text-white">
                    运行中
                  </div>
                  <div className="flex items-center justify-between text-xs mb-1.5">
                    <span className="font-code text-[11px] text-purple-300 font-semibold">
                      02. 交叉验证
                    </span>
                    <span className="w-1.5 h-1.5 rounded-full bg-purple-400 animate-pulse" />
                  </div>
                  <p className="text-xs text-white font-medium truncate">
                    证据链一致性核对
                  </p>
                  <p className="font-code text-[10px] text-purple-200 mt-1">
                    置信度: 98.4%
                  </p>
                </div>
                {/* Agent 3 */}
                <div className="p-3 rounded-lg bg-white/[0.03] border border-white/10 hover:border-purple-500/40 transition-colors">
                  <div className="flex items-center justify-between text-xs mb-1.5">
                    <span className="font-code text-[11px] text-neutral-400 font-semibold">
                      03. 研报生成
                    </span>
                    <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                  </div>
                  <p className="text-xs text-neutral-200 font-medium truncate">
                    结论与决策矩阵拟合
                  </p>
                  <p className="font-code text-[10px] text-neutral-400 mt-1">
                    排队待汇总
                  </p>
                </div>
              </div>

              {/* Streaming Synthesis Terminal View */}
              <div className="mt-4 p-3.5 rounded-lg bg-[#0a0c12] border border-white/5 font-code text-xs space-y-1.5">
                <div className="flex items-center justify-between text-[11px] text-neutral-400 pb-1.5 border-b border-white/5">
                  <span className="flex items-center gap-1.5">
                    <span className="material-symbols-outlined text-[13px] text-purple-400" style={{ fontSize: "13px" }}>
                      terminal
                    </span>
                    <span>live-stream // report_gen_task_892b.md</span>
                  </span>
                  <span className="text-[10px] text-emerald-400">
                    ● 实时写入中
                  </span>
                </div>
                <p className="text-neutral-300 leading-relaxed text-[11px] pt-1">
                  <span className="text-purple-400">» [Agent-02]:</span>{" "}
                  经对比 12 家主流 Foundry 财报与 IEEE 最新微架构测试基准，3nm
                  GAA 漏电抑制指标已收敛。
                </p>
                <p className="text-neutral-400 leading-relaxed text-[11px]">
                  <span className="text-neutral-500">» [System]:</span>{" "}
                  自动生成架构演进决策雷达图，预计 2.4s
                  后完成研报终审...
                  <span className="inline-block w-1.5 h-3.5 bg-purple-400 align-middle animate-pulse ml-0.5" />
                </p>
              </div>
            </div>

            {/* Metric Highlight Bar */}
            <div className="mt-3 pt-3 border-t border-white/5 grid grid-cols-3 gap-2 text-center">
              <div>
                <div className="font-code text-base font-semibold text-white">
                  10x
                </div>
                <div className="text-[10px] text-neutral-400">文献提取提速</div>
              </div>
              <div className="border-x border-white/5">
                <div className="font-code text-base font-semibold text-purple-300">
                  0%
                </div>
                <div className="text-[10px] text-neutral-400">外部数据外流</div>
              </div>
              <div>
                <div className="font-code text-base font-semibold text-white">
                  40k+
                </div>
                <div className="text-[10px] text-neutral-400">研究员已接入</div>
              </div>
            </div>
          </div>
        </div>

        {/* Bottom Testimonial Quote & Authority Endorsement */}
        <div className="relative z-10 pt-4 border-t border-white/10">
          <blockquote className="text-sm sm:text-base text-neutral-300 font-normal leading-relaxed italic">
            “Argus
            让我们的架构师团队从数千篇 SEC 报告与 ArXiv
            论文中自动化提炼关键决策点，原本需要两周的研报周期缩短到了两个小时，研究效率提升了
            10 倍以上。”
          </blockquote>
          <div className="mt-3 flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-purple-500 to-indigo-400 flex items-center justify-center font-bold text-xs text-white shadow">
                L
              </div>
              <div>
                <div className="text-xs font-semibold text-white">
                  某头部半导体实验室首席架构师
                </div>
                <div className="text-[11px] text-neutral-400 font-code">
                  Silicon Core Lab · Global Research
                </div>
              </div>
            </div>
            <div className="text-[11px] text-neutral-500 font-code">
              © 2026 Argus Systems Inc.
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}