// Typed wrappers around the SynTrack REST API. All endpoints share /api prefix.

import type {
  AlignmentResponse,
  BlocksResponse,
  ConfigResponse,
  FishDensityResponse,
  FishListResponse,
  FishSetResponse,
  FishSetScmsResponse,
  GenomesResponse,
  HighlightResponse,
  PairsResponse,
  PaintResponse,
  SCMResponse,
  SCMsResponse,
} from './types'

import { sessionHeaders } from './session'

const API_BASE = '/api'

type QueryValue = string | number | undefined | null

/** API failure carrying the HTTP status, so callers can recover from a
 *  specific code (404 for a set the server forgot, 409 for a label another
 *  browser session already took) instead of matching on the message. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly path: string,
    readonly body: string,
    readonly statusText: string,
  ) {
    super(`API ${status} ${statusText} on ${path}: ${body}`)
    this.name = 'ApiError'
  }
}

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
    headers: {
      Accept: 'application/json',
      // Namespaces this browser's FISH marker sets; ignored by every other
      // endpoint (docs/design/FISH_SESSION_SCOPE.md).
      ...sessionHeaders(),
      ...(init.headers ?? {}),
    },
    ...init,
  })
  if (!resp.ok) {
    const body = await resp.text()
    throw new ApiError(resp.status, path, body, resp.statusText)
  }
  return (await resp.json()) as T
}

export type RegionParams = {
  region_g1?: string
  region_g2?: string
}

export type ReferenceParam = {
  reference?: string
}

export const api = {
  genomes: (signal?: AbortSignal) =>
    request<GenomesResponse>('/genomes', {}, { signal }),

  pairs: (signal?: AbortSignal) =>
    request<PairsResponse>('/pairs', {}, { signal }),

  blocks: (
    g1: string,
    g2: string,
    opts: RegionParams & ReferenceParam & { min_scm?: number } = {},
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
    opts: RegionParams & ReferenceParam & { limit?: number } = {},
    signal?: AbortSignal,
  ) =>
    request<SCMsResponse>(
      '/synteny/scms',
      { g1, g2, ...opts },
      { signal },
    ),

  scm: (scmId: string, signal?: AbortSignal) =>
    request<SCMResponse>(`/scm/${encodeURIComponent(scmId)}`, {}, { signal }),

  paint: (genomeId: string, reference: string, signal?: AbortSignal) =>
    request<PaintResponse>('/paint', { genome_id: genomeId, reference }, { signal }),

  align: (
    genomeId: string,
    seq: string,
    pos: number,
    opts: { k?: number; targets?: string[] } = {},
    signal?: AbortSignal,
  ) => {
    const { targets, ...scalar } = opts
    const url = new URL(API_BASE + '/align', window.location.origin)
    url.searchParams.set('genome_id', genomeId)
    url.searchParams.set('seq', seq)
    url.searchParams.set('pos', String(pos))
    if (scalar.k !== undefined) url.searchParams.set('k', String(scalar.k))
    if (targets) for (const t of targets) url.searchParams.append('targets', t)
    return fetch(url, {
      headers: { Accept: 'application/json', ...sessionHeaders() },
      signal,
    }).then(async (resp) => {
      if (!resp.ok) {
        const body = await resp.text()
        throw new ApiError(resp.status, '/align', body, resp.statusText)
      }
      return (await resp.json()) as AlignmentResponse
    })
  },

  highlight: (
    genomeId: string,
    region: string,
    opts: { limit?: number } = {},
    signal?: AbortSignal,
  ) =>
    request<HighlightResponse>(
      '/highlight',
      { genome_id: genomeId, region, ...opts },
      { signal },
    ),

  config: (signal?: AbortSignal) =>
    request<ConfigResponse>('/config', {}, { signal }),

  fishCreate: (scm_ids: string[], label: string, color: string, replace = false) =>
    request<FishSetResponse>('/fish', {}, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scm_ids, label, color, replace }),
    }),

  fishList: () => request<FishListResponse>('/fish'),

  /** One stored set with its positions — used to rebuild the sidebar on load. */
  fishGet: (label: string) =>
    request<FishSetResponse>(`/fish/${encodeURIComponent(label)}`),

  fishDelete: (label: string) =>
    request<void>(`/fish/${encodeURIComponent(label)}`, {}, { method: 'DELETE' }),

  fishDensity: (bins: number, labels?: string[], signal?: AbortSignal) =>
    request<FishDensityResponse>('/fish/density', {}, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(labels ? { bins, labels } : { bins }),
      signal,
    }),

  fishScms: (label: string, signal?: AbortSignal) =>
    request<FishSetScmsResponse>(`/fish/${encodeURIComponent(label)}/scms`, {}, { signal }),
}
