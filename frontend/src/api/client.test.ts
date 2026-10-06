import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from './client'
import { SESSION_HEADER, resetSessionIdCache, sessionId } from './session'

/** Captured fetch calls, so we can assert on what actually goes on the wire. */
let calls: { url: string; init: RequestInit }[]

function headersOf(init: RequestInit): Record<string, string> {
  return (init.headers ?? {}) as Record<string, string>
}

beforeEach(() => {
  calls = []
  window.localStorage.clear()
  resetSessionIdCache()
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: URL | string, init: RequestInit = {}) => {
      calls.push({ url: String(url), init })
      return new Response(JSON.stringify({ sets: [], usage: null }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('session header', () => {
  it('is sent on a GET', async () => {
    await api.fishList()
    expect(headersOf(calls[0].init)[SESSION_HEADER]).toBe(sessionId())
  })

  it('is sent on a POST that also sets Content-Type', async () => {
    // Regression: `...init` used to be spread after `headers`, so a caller's
    // headers replaced the merged object and this header was dropped. Uploads
    // then landed in the shared "default" namespace while reads looked in this
    // browser's own session, and a stored set could not be found again.
    await api.fishCreate(['OG01'], 'label', '#ff0000')
    const headers = headersOf(calls[0].init)
    expect(headers[SESSION_HEADER]).toBe(sessionId())
    expect(headers['Content-Type']).toBe('application/json')
    expect(headers.Accept).toBe('application/json')
  })

  it('is sent on every method, with the same value', async () => {
    await api.fishCreate(['OG01'], 'l', '#ff0000')
    await api.fishList()
    await api.fishGet('l')
    await api.fishScms('l')
    await api.fishDensity(10, ['l'])
    await api.fishDelete('l')
    const seen = calls.map((c) => headersOf(c.init)[SESSION_HEADER])
    expect(seen).toHaveLength(6)
    expect(new Set(seen).size).toBe(1)
    expect(seen[0]).toBe(sessionId())
  })

  it('does not lose the caller method or body', async () => {
    await api.fishCreate(['OG01'], 'l', '#ff0000')
    expect(calls[0].init.method).toBe('POST')
    expect(JSON.parse(String(calls[0].init.body))).toMatchObject({
      label: 'l',
      scm_ids: ['OG01'],
    })
  })

  it('is sent on the hand-rolled /align request too', async () => {
    await api.align('g1', 'chr1', 100)
    expect(headersOf(calls[0].init)[SESSION_HEADER]).toBe(sessionId())
  })
})

describe('highlight export request', () => {
  it('sends limit=0 rather than dropping it as falsy', async () => {
    // The uncapped fetch behind the "↓ SCM IDs" button. request() skips
    // undefined/null params; 0 must survive, or the export would silently
    // download the capped (subsampled) overlay set instead of the full one.
    await api.highlight('g1', 'chr1:0-1000', { limit: 0 })
    const url = new URL(calls[0].url)
    expect(url.searchParams.get('limit')).toBe('0')
    expect(url.searchParams.get('genome_id')).toBe('g1')
    expect(url.searchParams.get('region')).toBe('chr1:0-1000')
  })

  it('omits limit when the caller does not ask for one', async () => {
    await api.highlight('g1', 'chr1:0-1000')
    expect(new URL(calls[0].url).searchParams.has('limit')).toBe(false)
  })
})
