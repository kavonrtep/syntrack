import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from './api/client'
import type { FishDensityResponse, FishSetResponse } from './api/types'
import {
  createFishSet,
  FishSetLostError,
  fishDensityRecovering,
  hydrateFishSets,
  recreateFishSet,
  withFishRetry,
  type FishApi,
  type FishStore,
} from './fish_recovery'

function resp(label: string, color = '#ff0000'): FishSetResponse {
  return { label, color, scm_count: 2, genome_coverage: {}, genomes: [] }
}

function density(labels: string[], missing: string[] = []): FishDensityResponse {
  return {
    bins: 4,
    sets: labels.map((label) => ({
      label,
      color: '#ff0000',
      scm_count: 1,
      max_count: 1,
      genomes: {},
    })),
    missing,
  }
}

/** In-memory stand-in for the component's three maps. */
function makeStore(initial: Record<string, string[]> = {}) {
  const sets = new Map<string, FishSetResponse>()
  const ids = new Map<string, string[]>()
  for (const [label, idList] of Object.entries(initial)) {
    sets.set(label, resp(label))
    ids.set(label, idList)
  }
  const reports: string[] = []
  const store: FishStore = {
    get: (l) => sets.get(l),
    set: (l, r) => void sets.set(l, r),
    ids: (l) => ids.get(l),
    setIds: (l, v) => void ids.set(l, v),
    drop: (l) => {
      sets.delete(l)
      ids.delete(l)
    },
    report: (m) => void reports.push(m),
  }
  return { store, sets, ids, reports }
}

const notFound = () => new ApiError(404, '/fish/x/scms', 'FISH set not found', 'Not Found')
const conflict = () => new ApiError(409, '/fish', 'already exists', 'Conflict')

let api: FishApi

beforeEach(() => {
  api = {
    create: vi.fn(async (_ids, label) => resp(label)),
    density: vi.fn(async (_bins, labels) => density(labels)),
    list: vi.fn(async () => []),
    get: vi.fn(async (label) => resp(label)),
    scmIds: vi.fn(async () => ['OG01']),
  }
})

describe('recreateFishSet', () => {
  it('re-POSTs the kept SCM IDs with replace and keeps the colour', async () => {
    const { store, sets } = makeStore({ s1: ['OG01', 'OG02'] })
    sets.set('s1', resp('s1', '#00ff00'))
    expect(await recreateFishSet('s1', store, api)).toBe(true)
    expect(api.create).toHaveBeenCalledWith(['OG01', 'OG02'], 's1', '#00ff00', true)
  })

  it('drops the set and reports when no IDs were kept', async () => {
    const { store, sets, reports } = makeStore()
    sets.set('ghost', resp('ghost'))
    expect(await recreateFishSet('ghost', store, api)).toBe(false)
    expect(sets.has('ghost')).toBe(false)
    expect(reports[0]).toMatch(/no longer on the server/)
    expect(api.create).not.toHaveBeenCalled()
  })

  it('drops the set when the server refuses the re-creation', async () => {
    const { store, sets, reports } = makeStore({ s1: ['OG01'] })
    api.create = vi.fn(async () => {
      throw new ApiError(500, '/fish', 'boom', 'Server Error')
    })
    expect(await recreateFishSet('s1', store, api)).toBe(false)
    expect(sets.has('s1')).toBe(false)
    expect(reports[0]).toMatch(/boom/)
  })
})

describe('withFishRetry', () => {
  it('re-creates the set and retries once on 404', async () => {
    const { store } = makeStore({ s1: ['OG01'] })
    const op = vi.fn()
    op.mockRejectedValueOnce(notFound()).mockResolvedValueOnce('ok')
    expect(await withFishRetry('s1', store, api, op)).toBe('ok')
    expect(op).toHaveBeenCalledTimes(2)
    expect(api.create).toHaveBeenCalledTimes(1)
  })

  it('does not retry a non-404 failure', async () => {
    const { store } = makeStore({ s1: ['OG01'] })
    const op = vi.fn(async () => {
      throw new ApiError(500, '/fish', 'boom', 'Server Error')
    })
    await expect(withFishRetry('s1', store, api, op)).rejects.toThrow(/500/)
    expect(op).toHaveBeenCalledTimes(1)
    expect(api.create).not.toHaveBeenCalled()
  })

  it('reports the real reason, not the stale 404, when the set cannot be restored', async () => {
    const { store } = makeStore() // no IDs kept
    const op = vi.fn(async () => {
      throw notFound()
    })
    const err = await withFishRetry('gone', store, api, op).catch((e: unknown) => e)
    expect(err).toBeInstanceOf(FishSetLostError)
    expect((err as Error).message).toMatch(/no longer on the server/)
    expect((err as Error).message).toMatch(/Re-import/)
    expect(op).toHaveBeenCalledTimes(1)
  })

  it('retries at most once — a second 404 surfaces', async () => {
    const { store } = makeStore({ s1: ['OG01'] })
    const op = vi.fn(async () => {
      throw notFound()
    })
    await expect(withFishRetry('s1', store, api, op)).rejects.toThrow(/404/)
    expect(op).toHaveBeenCalledTimes(2)
  })
})

describe('createFishSet', () => {
  it('stores the response on a clean create', async () => {
    const { store, sets } = makeStore()
    await createFishSet(['OG01'], 's1', '#ff0000', store, api)
    expect(api.create).toHaveBeenCalledWith(['OG01'], 's1', '#ff0000')
    expect(sets.get('s1')?.label).toBe('s1')
  })

  it('takes the label over when another session holds it (409)', async () => {
    const { store, sets } = makeStore()
    const create = vi.fn(async (_ids: string[], label: string) => resp(label))
    create.mockRejectedValueOnce(conflict())
    api.create = create
    await createFishSet(['OG01'], 's1', '#ff0000', store, api)
    expect(create).toHaveBeenCalledTimes(2)
    expect(create).toHaveBeenLastCalledWith(['OG01'], 's1', '#ff0000', true)
    expect(sets.has('s1')).toBe(true)
  })
})

describe('fishDensityRecovering', () => {
  it('passes a clean response straight through', async () => {
    const { store } = makeStore({ s1: ['OG01'] })
    const out = await fishDensityRecovering(4, ['s1'], store, api)
    expect(out.sets.map((s) => s.label)).toEqual(['s1'])
    expect(api.density).toHaveBeenCalledTimes(1)
  })

  it('re-creates missing sets and retries once with the survivors', async () => {
    const { store } = makeStore({ live: ['OG01'], lost: ['OG02'] })
    const dens = vi.fn(async (_b: number, labels: string[]) => density(labels))
    dens.mockResolvedValueOnce(density(['live'], ['lost']))
    api.density = dens
    const out = await fishDensityRecovering(4, ['live', 'lost'], store, api)
    expect(api.create).toHaveBeenCalledWith(['OG02'], 'lost', '#ff0000', true)
    expect(dens).toHaveBeenCalledTimes(2)
    expect(out.sets.map((s) => s.label)).toEqual(['live', 'lost'])
  })

  it('keeps the preview for the sets that resolved when one cannot be restored', async () => {
    const { store, sets, reports } = makeStore({ live: ['OG01'] })
    sets.set('ghost', resp('ghost')) // present but no IDs -> unrecoverable
    api.density = vi.fn(async () => density(['live'], ['ghost']))
    const out = await fishDensityRecovering(4, ['live', 'ghost'], store, api)
    expect(out.sets.map((s) => s.label)).toEqual(['live'])
    expect(sets.has('ghost')).toBe(false)
    expect(reports[0]).toMatch(/no longer on the server/)
    expect(api.density).toHaveBeenCalledTimes(1) // no pointless retry
  })
})

describe('hydrateFishSets', () => {
  it('restores each set together with the SCM IDs needed to re-assert it', async () => {
    const { store, sets, ids } = makeStore()
    api.list = vi.fn(async () => ['s1', 's2'])
    api.scmIds = vi.fn(async (label: string) => [`${label}-OG01`])
    expect(await hydrateFishSets(store, api)).toEqual(['s1', 's2'])
    expect([...sets.keys()]).toEqual(['s1', 's2'])
    expect(ids.get('s1')).toEqual(['s1-OG01'])
  })

  it('a hydrated set is then self-healing (the v0.5.0 gap)', async () => {
    const { store } = makeStore()
    api.list = vi.fn(async () => ['s1'])
    await hydrateFishSets(store, api)
    // Server loses the set; the next operation must recover rather than fail.
    const op = vi.fn()
    op.mockRejectedValueOnce(notFound()).mockResolvedValueOnce('ok')
    expect(await withFishRetry('s1', store, api, op)).toBe('ok')
  })

  it('drops a set whose IDs cannot be fetched instead of leaving a dead entry', async () => {
    const { store, sets, reports } = makeStore()
    api.list = vi.fn(async () => ['s1'])
    api.scmIds = vi.fn(async () => {
      throw notFound()
    })
    expect(await hydrateFishSets(store, api)).toEqual([])
    expect(sets.has('s1')).toBe(false)
    expect(reports[0]).toMatch(/could not be fully restored/)
  })

  it('skips a set that vanishes between the list and the fetch', async () => {
    const { store, sets } = makeStore()
    api.list = vi.fn(async () => ['gone', 'ok'])
    api.get = vi.fn(async (label: string) => {
      if (label === 'gone') throw notFound()
      return resp(label)
    })
    expect(await hydrateFishSets(store, api)).toEqual(['ok'])
    expect(sets.has('gone')).toBe(false)
  })

  it('treats an unreachable server as an empty sidebar, not an error', async () => {
    const { store, reports } = makeStore()
    api.list = vi.fn(async () => {
      throw new ApiError(500, '/fish', 'down', 'Server Error')
    })
    expect(await hydrateFishSets(store, api)).toEqual([])
    expect(reports).toEqual([])
  })
})
