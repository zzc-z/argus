import * as React from 'react'

/**
 * /(error) route group — minimal chrome for full-screen error pages.
 *
 * Why: a server-fault (500) page should not show the dashboard sidebar.
 * The sidebar itself is part of the app surface that may be unhealthy; if
 * we render it during a 500 the user sees broken nav links on top of the
 * diagnostic, which doubles their anxiety. 404 stays in (dashboard) so
 * the user can escape via the menu; 500 alone comes here.
 *
 * No sidebar, no topbar, no global search — only the page itself.
 * Centred, scrollable, with safe-area padding for the OS chrome.
 */
export default function ErrorLayout({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        minHeight: '100vh',
        width: '100%',
        backgroundColor: 'var(--token-surface, #f8f9fa)',
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'center',
        padding: '3rem 1.5rem 4rem',
      }}
    >
      {children}
    </div>
  )
}
