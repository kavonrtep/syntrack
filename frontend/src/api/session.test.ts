import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { SESSION_HEADER, resetSessionIdCache, sessionHeaders, sessionId } from './session'

const KEY = 'syntrack.session_id'

beforeEach(() => {
  window.localStorage.clear()
  resetSessionIdCache()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('sessionId', () => {
  it('generates an ID once and reuses it within a page', () => {
    const first = sessionId()
    expect(first).toBeTruthy()
    expect(sessionId()).toBe(first)
  })

  it('persists across reloads (a fresh cache re-reads storage)', () => {
    const first = sessionId()
    resetSessionIdCache() // as if the page had reloaded
    expect(sessionId()).toBe(first)
    expect(window.localStorage.getItem(KEY)).toBe(first)
  })

  it('adopts an ID already in storage rather than minting a new one', () => {
    window.localStorage.setItem(KEY, 'pre-existing')
    expect(sessionId()).toBe('pre-existing')
  })

  it('replaces a blank stored value', () => {
    window.localStorage.setItem(KEY, '   ')
    const id = sessionId()
    expect(id.trim()).toBe(id)
    expect(id).not.toBe('   ')
  })

  it('still yields an ID when storage throws (private mode)', () => {
    vi.spyOn(window.localStorage, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(sessionId()).toBeTruthy()
  })

  it('does not reuse one browser ID for a different storage (two browsers differ)', () => {
    const a = sessionId()
    window.localStorage.clear()
    resetSessionIdCache()
    expect(sessionId()).not.toBe(a)
  })
})

describe('sessionHeaders', () => {
  it('sends the ID under the agreed header name', () => {
    expect(sessionHeaders()).toEqual({ [SESSION_HEADER]: sessionId() })
  })
})
