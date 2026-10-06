import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from './api/client'
import type { FishDensityResponse, FishSetResponse, FishUsage } from './api/types'
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

function usage(sets = 1, bytes = 4): FishUsage {
  return {
    session_sets: sets,
    max_sets: 512,
    session_bytes: bytes,
    total_bytes: bytes,
    max_bytes: 128 * 1024 * 1024,
    sessions: 1,
  }
}

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
  const seenUsage: (FishUsage | null | undefined)[] = []
  const revisions = new Map<string, number>()
  const bump = (l: string) => void revisions.set(l, (revisions.get(l) ?? 0) + 1)
  const store: FishStore = {
    get: (l) => sets.get(l),
    set: (l, r) => {
      sets.set(l, r)
      bump(l)
    },
    ids: (l) => ids.get(l),
    setIds: (l, v) => {
      ids.set(l, v)
      bump(l)
    },
    drop: (l) => {
      sets.delete(l)
      ids.delete(l)
      bump(l)
    },
    revision: (l) => revisions.get(l) ?? 0,
    report: (m) => void reports.push(m),
    setUsage: (u) => void seenUsage.push(u),
  }
  return { store, sets, ids, reports, seenUsage, bump }
}

const notFound = () => new ApiError(404, '/fish/x/scms', 'FISH set not found', 'Not Found')
const conflict = () => new ApiError(409, '/fish', 'already exists', 'Conflict')

let api: FishApi

beforeEach(() => {
  api = {
    create: vi.fn(async (_ids, label) => resp(label)),
    density: vi.fn(async (_bins, labels) => density(labels)),
    list: vi.fn(async () => ({ labels: [] as string[], usage: usage(0, 0) })),
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
    api.list = vi.fn(async () => ({ labels: ['s1', 's2'], usage: usage() }))
    api.scmIds = vi.fn(async (label: string) => [`${label}-OG01`])
    expect(await hydrateFishSets(store, api)).toEqual(['s1', 's2'])
    expect([...sets.keys()]).toEqual(['s1', 's2'])
    expect(ids.get('s1')).toEqual(['s1-OG01'])
  })

  it('a hydrated set is then self-healing (the v0.5.0 gap)', async () => {
    const { store } = makeStore()
    api.list = vi.fn(async () => ({ labels: ['s1'], usage: usage() }))
    await hydrateFishSets(store, api)
    // Server loses the set; the next operation must recover rather than fail.
    const op = vi.fn()
    op.mockRejectedValueOnce(notFound()).mockResolvedValueOnce('ok')
    expect(await withFishRetry('s1', store, api, op)).toBe('ok')
  })

  it('drops a set whose IDs cannot be fetched instead of leaving a dead entry', async () => {
    const { store, sets, reports } = makeStore()
    api.list = vi.fn(async () => ({ labels: ['s1'], usage: usage() }))
    api.scmIds = vi.fn(async () => {
      throw notFound()
    })
    expect(await hydrateFishSets(store, api)).toEqual([])
    expect(sets.has('s1')).toBe(false)
    expect(reports[0]).toMatch(/could not be fully restored/)
  })

  it('skips a set that vanishes between the list and the fetch', async () => {
    const { store, sets } = makeStore()
    api.list = vi.fn(async () => ({ labels: ['gone', 'ok'], usage: usage() }))
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

describe('budget reporting', () => {
  it('records the budget the server returns when a set is created', async () => {
    const { store, seenUsage } = makeStore()
    api.create = vi.fn(async (_ids: string[], label: string) => ({
      ...resp(label),
      usage: usage(3, 1024),
    }))
    await createFishSet(['OG01'], 's1', '#ff0000', store, api)
    expect(seenUsage.at(-1)).toMatchObject({ session_sets: 3, session_bytes: 1024 })
  })

  it('records the budget on hydration', async () => {
    const { store, seenUsage } = makeStore()
    api.list = vi.fn(async () => ({ labels: ['s1'], usage: usage(7, 2048) }))
    await hydrateFishSets(store, api)
    expect(seenUsage[0]).toMatchObject({ session_sets: 7, session_bytes: 2048 })
  })

  it('records the budget after a set is re-asserted', async () => {
    const { store, seenUsage } = makeStore({ s1: ['OG01'] })
    api.create = vi.fn(async (_ids: string[], label: string) => ({
      ...resp(label),
      usage: usage(2, 512),
    }))
    await recreateFishSet('s1', store, api)
    expect(seenUsage.at(-1)).toMatchObject({ session_sets: 2 })
  })
})

describe('hydration races with the user', () => {
  /** A deferred promise, so a hydration request can be held open while the
   *  user re-imports the same label. */
  /** Pump microtasks until `ready` holds, so the interleaving under test is
   *  deterministic rather than dependent on how many awaits hydration has
   *  gone through. */
  async function until(ready: () => boolean): Promise<void> {
    for (let i = 0; i < 100 && !ready(); i++) await Promise.resolve()
    expect(ready()).toBe(true)
  }

  function deferred<T>() {
    let resolve!: (v: T) => void
    let reject!: (e: unknown) => void
    const promise = new Promise<T>((res, rej) => {
      resolve = res
      reject = rej
    })
    return { promise, resolve, reject }
  }

  it('does not overwrite IDs of a set re-imported while restoration is in flight', async () => {
    const { store, ids, bump } = makeStore()
    api.list = vi.fn(async () => ({ labels: ['s1'], usage: usage() }))
    const pending = deferred<string[]>()
    api.scmIds = vi.fn(() => pending.promise)

    const hydrating = hydrateFishSets(store, api)
    await until(() => vi.mocked(api.scmIds).mock.calls.length > 0)

    // The user re-imports the same label with different membership.
    store.set('s1', resp('s1'))
    store.setIds('s1', ['NEW01', 'NEW02'])
    bump('s1')

    pending.resolve(['OLD01']) // the stale response finally lands
    await hydrating

    expect(ids.get('s1')).toEqual(['NEW01', 'NEW02'])
  })

  it('does not drop a set re-imported while its restoration was failing', async () => {
    const { store, sets, ids, reports, bump } = makeStore()
    api.list = vi.fn(async () => ({ labels: ['s1'], usage: usage() }))
    const pending = deferred<string[]>()
    api.scmIds = vi.fn(() => pending.promise)

    const hydrating = hydrateFishSets(store, api)
    await until(() => vi.mocked(api.scmIds).mock.calls.length > 0)

    store.set('s1', resp('s1'))
    store.setIds('s1', ['NEW01'])
    bump('s1')

    pending.reject(notFound()) // restoration fails after the user's import
    await hydrating

    expect(sets.has('s1')).toBe(true)
    expect(ids.get('s1')).toEqual(['NEW01'])
    expect(reports).toEqual([])
  })

  it('does not overwrite a set re-imported while its GET was in flight', async () => {
    const { store, sets, ids, bump } = makeStore()
    api.list = vi.fn(async () => ({ labels: ['s1'], usage: usage() }))
    const pending = deferred<FishSetResponse>()
    api.get = vi.fn(() => pending.promise)

    const hydrating = hydrateFishSets(store, api)
    await until(() => vi.mocked(api.get).mock.calls.length > 0)

    store.set('s1', resp('s1', '#00ff00'))
    store.setIds('s1', ['NEW01'])
    bump('s1')

    pending.resolve(resp('s1', '#ff0000'))
    await hydrating

    expect(sets.get('s1')?.color).toBe('#00ff00')
    expect(ids.get('s1')).toEqual(['NEW01'])
    expect(api.scmIds).not.toHaveBeenCalled()
  })

  it('still restores labels the user did not touch', async () => {
    const { store, ids } = makeStore()
    api.list = vi.fn(async () => ({ labels: ['quiet'], usage: usage() }))
    api.scmIds = vi.fn(async () => ['OG01'])
    expect(await hydrateFishSets(store, api)).toEqual(['quiet'])
    expect(ids.get('quiet')).toEqual(['OG01'])
  })
})
