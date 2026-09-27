'use client'

/**
 * /explore — Argus multi-agent deep research console.
 *
 * Restoration of argus_2/code.html. This page intentionally diverges from
 * the project's Material 3 token system: argus_2 has its own dark surface
 * palette (#0a0a0a bg + #4f7cff brand + #7039f9 accent) and Inter as the
 * primary UI font, which we load per-page via next/font/google so other
 * routes (Geist) are unaffected.
 *
 * Layout (1440px wrapper, sticky 56px TopBar):
 *   ┌──────────────────────────────────────────────┐
 *   │ TopBar (brand, search, live, toggle, avatar) │
 *   ├─────────────────────────────────┬────────────┤
 *   │ Center column (920px)           │ Inspector  │
 *   │  ├ AgentDAG (5 nodes)           │ (380px)    │
 *   │  ├ StreamingReport (H1 + prose) │ collapsible│
 *   │  │  └ cite-sup + metrics card   │            │
 *   └─────────────────────────────────┴────────────┘
 *           ┌──────────────────────────┐
 *           │ PromptInput (48px fixed) │
 *           └──────────────────────────┘
 */

import * as React from 'react'
import { Inter } from 'next/font/google'

import { TopBar } from './components/TopBar'
import { AgentDAG } from './components/AgentDAG'
import { StreamingReport } from './components/StreamingReport'
import {
  InspectorDrawer,
  getDefaultInspectorPayload,
  buildNodePayload,
  buildCitationPayload,
  type InspectorPayload,
} from './components/InspectorDrawer'
import { PromptInput } from './components/PromptInput'
import type { SlashCommand } from './mock'
import styles from './page.module.css'

const inter = Inter({
  subsets: ['latin'],
  display: 'swap',
  weight: ['400', '500', '600'],
})

export default function ExplorePage() {
  const [inspectorOpen, setInspectorOpen] = React.useState(true)
  const [inspectorPayload, setInspectorPayload] = React.useState<InspectorPayload>(() =>
    getDefaultInspectorPayload(),
  )

  const [promptValue, setPromptValue] = React.useState('')
  // Popover is visible when value starts with "/" (and is exactly "/", per
  // design — typing more characters hides it again).
  const slashVisible = promptValue === '/'

  const handleSelectNode = React.useCallback((node: Parameters<typeof buildNodePayload>[0]) => {
    setInspectorOpen(true)
    setInspectorPayload(buildNodePayload(node))
  }, [])

  const handleSelectCitation = React.useCallback(
    (citation: Parameters<typeof buildCitationPayload>[0]) => {
      setInspectorOpen(true)
      setInspectorPayload(buildCitationPayload(citation))
    },
    [],
  )

  const handleToggleInspector = React.useCallback(() => {
    setInspectorOpen((v) => !v)
  }, [])

  const handleCloseInspector = React.useCallback(() => {
    setInspectorOpen(false)
  }, [])

  const handlePromptSubmit = React.useCallback((value: string) => {
    // Stub: real submit would route to a chat handler. For now we just
    // clear the input — design has no console.log spam.
    setPromptValue('')
    void value
  }, [])

  const handleSlashSelect = React.useCallback((cmd: SlashCommand) => {
    setPromptValue(`${cmd.cmd} `)
  }, [])

  return (
    <div className={`${styles.shell} ${inter.className}`}>
      <TopBar onToggleInspector={handleToggleInspector} inspectorOpen={inspectorOpen} />

      <div className={styles.main}>
        {/* Center column: DAG + Streaming Report */}
        <main className={styles.center}>
          <AgentDAG onSelectNode={handleSelectNode} />
          <StreamingReport onSelectCitation={handleSelectCitation} />
        </main>

        {/* Right inspector (collapsible) */}
        <InspectorDrawer
          open={inspectorOpen}
          payload={inspectorPayload}
          onClose={handleCloseInspector}
        />
      </div>

      {/* Fixed bottom prompt input */}
      <div className={styles.bottomBar}>
        <div className={styles.bottomInner}>
          <PromptInput
            value={promptValue}
            onChange={setPromptValue}
            onSubmit={handlePromptSubmit}
            slashVisible={slashVisible}
            onSlashSelect={handleSlashSelect}
          />
        </div>
      </div>
    </div>
  )
}
