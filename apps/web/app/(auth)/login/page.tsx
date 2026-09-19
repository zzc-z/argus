import Link from 'next/link';
import { ArgusLogo } from '@/components/ArgusLogo';

export default function LoginPage() {
  return (
    <main className="min-h-screen flex flex-col lg:flex-row">
      <section className="w-full lg:w-[46%] xl:w-[44%] flex flex-col justify-between bg-surface-container-lowest border-r border-surface-container-high/70 px-6 sm:px-12 md:px-16 lg:px-14 xl:px-20 py-8 lg:py-10">
        <header className="flex items-center justify-between w-full">
          <div className="flex items-center gap-3">
            <ArgusLogo className="w-9 h-9" />
            <div className="flex items-center gap-2">
              <span className="font-semibold tracking-tight text-on-surface">Argus</span>
              <span className="font-medium tracking-tight text-[11px] text-primary-container bg-primary-fixed/70 border border-primary-fixed-dim px-2 py-0.5 rounded-full">
                v2.4 Tech Preview
              </span>
            </div>
          </div>
          <div className="flex items-center gap-2 text-secondary text-sm">
            <Link href="#" className="hidden sm:flex items-center gap-1 hover:text-on-surface transition-colors text-xs font-medium">
              <span aria-hidden="true">?</span>
              <span>文档中心</span>
            </Link>
            <span className="hidden sm:inline text-outline-variant font-code text-xs">/</span>
            <button className="flex items-center gap-1 px-2 py-1 rounded hover:bg-surface-container-low text-xs text-on-surface-variant transition-colors border border-transparent hover:border-surface-container">
              <span aria-hidden="true">文</span>
              <span>简中</span>
            </button>
          </div>
        </header>

        <div className="my-auto py-10 w-full max-w-[420px] mx-auto">
          <div className="mb-8">
            <h1 className="text-2xl sm:text-[28px] font-semibold tracking-tight text-on-surface">
              登录您的研究工作台
            </h1>
            <p className="text-sm text-secondary mt-2 leading-relaxed">
              多智能体深度研报 · 面向工程师与研究员的 AI 洞察引擎
            </p>
          </div>

          <div className="space-y-3">
            <button className="group relative w-full flex items-center justify-between px-4 py-3 bg-[#16191f] hover:bg-[#0d1015] active:scale-[0.99] text-white rounded-lg transition-all duration-150 shadow-sm border border-neutral-800">
              <div className="flex items-center gap-3">
                <svg className="w-5 h-5 fill-current transition-transform duration-200 group-hover:scale-105" viewBox="0 0 24 24">
                  <path clipRule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" fillRule="evenodd" />
                </svg>
                <span className="text-sm font-medium tracking-tight">使用 GitHub 账号继续</span>
              </div>
              <div className="flex items-center gap-1.5">
                <kbd className="font-mono text-[11px] text-neutral-400 bg-neutral-800/80 px-1.5 py-0.5 rounded border border-neutral-700">⌘G</kbd>
                <span aria-hidden="true" className="text-[16px] text-neutral-400 group-hover:translate-x-0.5 transition-transform">→</span>
              </div>
            </button>

            <button className="group relative w-full flex items-center justify-between px-4 py-3 bg-surface-container-lowest hover:bg-surface-container-low active:scale-[0.99] text-on-surface rounded-lg transition-all duration-150 shadow-xs border border-surface-container-highest">
              <div className="flex items-center gap-3">
                <svg className="w-5 h-5 flex-shrink-0" viewBox="0 0 24 24">
                  <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4" />
                  <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
                  <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z" fill="#FBBC05" />
                  <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z" fill="#EA4335" />
                </svg>
                <span className="text-sm font-medium tracking-tight">使用 Google Workspace 账号继续</span>
              </div>
              <div className="flex items-center gap-1.5">
                <kbd className="font-mono text-[11px] text-secondary bg-surface-container px-1.5 py-0.5 rounded border border-surface-container-high">⌘W</kbd>
                <span aria-hidden="true" className="text-[16px] text-secondary group-hover:translate-x-0.5 transition-transform">→</span>
              </div>
            </button>
          </div>

          <p className="text-xs text-outline text-center mt-6 leading-relaxed">
            继续即表示您同意 Argus 的 <Link href="#" className="underline hover:text-on-surface-variant">服务条款</Link> 与 <Link href="#" className="underline hover:text-on-surface-variant">隐私政策</Link>。
          </p>
        </div>

        <footer className="text-xs text-outline">
          <div className="flex items-center justify-between w-full">
            <span>© 2026 Argus · 私有部署</span>
            <div className="flex items-center gap-3">
              <Link href="#" className="hover:text-on-surface-variant">状态</Link>
              <Link href="#" className="hover:text-on-surface-variant">安全</Link>
              <Link href="#" className="hover:text-on-surface-variant">变更日志</Link>
            </div>
          </div>
        </footer>
      </section>

      <aside className="hidden lg:flex flex-1 relative overflow-hidden bg-surface-container-lowest border-l border-surface-container-high/70 items-center justify-center p-12">
        <div className="absolute inset-0 opacity-40 pointer-events-none" style={{ backgroundImage: 'radial-gradient(rgba(112, 57, 249, 0.18) 1.2px, transparent 1.2px)', backgroundSize: '24px 24px' }} />
        <div className="relative max-w-md text-center space-y-6">
          <div className="text-7xl font-semibold tracking-tight text-primary-container/30 select-none">Argus</div>
          <p className="text-base text-secondary leading-relaxed">
            百眼巨人 · 多智能体前沿调研引擎<br />
            监督者调度 · 研究者采集 · 分析师去重 · 写作者输出 · 批判者自检
          </p>
        </div>
      </aside>
    </main>
  );
}
