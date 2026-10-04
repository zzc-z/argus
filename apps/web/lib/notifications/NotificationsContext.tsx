'use client'

import * as React from 'react'
import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef } from 'react'

import type {
  NotificationCategory,
  NotificationSeverity,
  NotificationWithMeta,
} from '@/app/(dashboard)/notifications/mock'

/**
 * NotificationsContext — cross-page state for user-pushed notifications.
 *
 * The /notifications page owns its own static mock (8 historical items
 * grouped into today / yesterday / earlier sections). This store carries
 * the *delta*: notifications created by other routes (e.g. /topics drawer
 * submitting a subscription, /add-sources finishing an ingestion) that
 * should appear in the notification center as fresh unread items.
 *
 * Persistence: localStorage key `argus:notifications-extra`. SSR renders
 * empty extras (matches mock fallback); client mounts → reads storage → dispatches
 * HYDRATE. New items pushed via `pushNotification` are appended in-memory
 * AND written to storage in the same effect cycle.
 *
 * Scope: PRD §6.1.3 close-the-loop demo. No real backend; no WebSocket.
 */

const STORAGE_KEY = 'argus:notifications-extra'

export interface NewNotificationInput {
  category: NotificationCategory
  severity: NotificationSeverity
  icon: string
  tag: string
  title: string
  body: string
  chips?: NotificationWithMeta['chips']
}

interface State {
  extras: NotificationWithMeta[]
  markedReadIds: Set<string>
}

type Action =
  | { type: 'PUSH'; item: NotificationWithMeta }
  | { type: 'MARK_READ'; id: string }
  | { type: 'MARK_ALL_READ' }
  | { type: 'DISMISS'; id: string }
  | { type: 'HYDRATE'; items: NotificationWithMeta[] }

const initialState: State = {
  extras: [],
  markedReadIds: new Set<string>(),
}

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'PUSH':
      return { ...state, extras: [action.item, ...state.extras] }
    case 'MARK_READ': {
      if (state.markedReadIds.has(action.id)) return state
      const next = new Set(state.markedReadIds)
      next.add(action.id)
      return { ...state, markedReadIds: next }
    }
    case 'MARK_ALL_READ': {
      if (state.extras.length === 0) return state
      const next = new Set(state.markedReadIds)
      for (const it of state.extras) next.add(it.id)
      return { ...state, markedReadIds: next }
    }
    case 'DISMISS':
      return {
        ...state,
        extras: state.extras.filter((it) => it.id !== action.id),
        markedReadIds: (() => {
          if (!state.markedReadIds.has(action.id)) return state.markedReadIds
          const next = new Set(state.markedReadIds)
          next.delete(action.id)
          return next
        })(),
      }
    case 'HYDRATE':
      return { ...state, extras: action.items }
  }
}

interface NotificationsContextValue {
  extras: NotificationWithMeta[]
  markedReadIds: Set<string>
  pushNotification: (input: NewNotificationInput) => void
  dismissNotification: (id: string) => void
  markRead: (id: string) => void
  markAllRead: () => void
}

const NotificationsContext = createContext<NotificationsContextValue | null>(null)

/** Format current time as "HH:MM" for the time field on pushed items. */
function nowHHMM(): string {
  const d = new Date()
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

export function NotificationsProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState)
  const counterRef = useRef(0)

  // HYDRATE on mount — read persisted extras from localStorage.
  useEffect(() => {
    if (typeof window === 'undefined') return
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY)
      if (!raw) return
      const parsed = JSON.parse(raw) as NotificationWithMeta[]
      if (Array.isArray(parsed) && parsed.length > 0) {
        dispatch({ type: 'HYDRATE', items: parsed })
      }
    } catch {
      // ignore corrupted storage
    }
  }, [])

  // PERSIST extras to localStorage whenever the list changes (post-mount only).
  useEffect(() => {
    if (typeof window === 'undefined') return
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state.extras))
    } catch {
      // quota / private-mode: silently ignore
    }
  }, [state.extras])

  const pushNotification = useCallback((input: NewNotificationInput) => {
    counterRef.current += 1
    const id = `push-${Date.now()}-${counterRef.current}`
    const item: NotificationWithMeta = {
      id,
      category: input.category,
      severity: input.severity,
      icon: input.icon,
      tag: input.tag,
      title: input.title,
      body: input.body,
      time: nowHHMM(),
      timeDetail: '刚刚',
      unread: true,
      chips: input.chips,
    }
    dispatch({ type: 'PUSH', item })
  }, [])

  const dismissNotification = useCallback((id: string) => {
    dispatch({ type: 'DISMISS', id })
  }, [])

  const markRead = useCallback((id: string) => {
    dispatch({ type: 'MARK_READ', id })
  }, [])

  const markAllRead = useCallback(() => {
    dispatch({ type: 'MARK_ALL_READ' })
  }, [])

  const value = useMemo<NotificationsContextValue>(
    () => ({
      extras: state.extras,
      markedReadIds: state.markedReadIds,
      pushNotification,
      dismissNotification,
      markRead,
      markAllRead,
    }),
    [state.extras, state.markedReadIds, pushNotification, dismissNotification, markRead, markAllRead],
  )

  return <NotificationsContext.Provider value={value}>{children}</NotificationsContext.Provider>
}

/** Read notifications store. Throws if used outside `<NotificationsProvider>`. */
export function useNotifications(): NotificationsContextValue {
  const ctx = useContext(NotificationsContext)
  if (!ctx) {
    throw new Error('useNotifications must be used within a <NotificationsProvider>')
  }
  return ctx
}
