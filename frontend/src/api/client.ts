// Typed wrappers around the SynTrack REST API. All endpoints share /api prefix.

import type {
  BlocksResponse,
  ConfigResponse,
  GenomesResponse,
  PairsResponse,
  SCMResponse,
  SCMsResponse,
} from './types'

const API_BASE = '/api'

type QueryValue = string | number | undefined | null

async function request<T>(
  path: string,
  params: Record<string, QueryValue> = {},
  init: RequestInit = {},
): Promise<T> {
  const url = new URL(API_BASE + path, window.location.origin)
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) {
      url.searchParams.set(key, String(value))
    }
  }
  const resp = await fetch(url, {
    headers: { Accept: 'application/json', ...(init.headers ?? {}) },
    ...init,
  })
  if (!resp.ok) {
    const body = await resp.text()
    throw new Error(`API ${resp.status} ${resp.statusText} on ${path}: ${body}`)
  }
  return (await resp.json()) as T
}

export type RegionParams = {
  region_g1?: string
  region_g2?: string
}

export const api = {
  genomes: (signal?: AbortSignal) =>
    request<GenomesResponse>('/genomes', {}, { signal }),

  pairs: (signal?: AbortSignal) =>
    request<PairsResponse>('/pairs', {}, { signal }),

  blocks: (
    g1: string,
    g2: string,
    opts: RegionParams & { min_scm?: number } = {},
    signal?: AbortSignal,
  ) =>
    request<BlocksResponse>(
      '/synteny/blocks',
      { g1, g2, ...opts },
      { signal },
    ),

  scms: (
    g1: string,
    g2: string,
    opts: RegionParams & { limit?: number } = {},
    signal?: AbortSignal,
  ) =>
    request<SCMsResponse>(
      '/synteny/scms',
      { g1, g2, ...opts },
      { signal },
    ),

  scm: (scmId: string, signal?: AbortSignal) =>
    request<SCMResponse>(`/scm/${encodeURIComponent(scmId)}`, {}, { signal }),

  config: (signal?: AbortSignal) =>
    request<ConfigResponse>('/config', {}, { signal }),
}
