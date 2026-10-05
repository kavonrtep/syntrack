/** Recovery logic for FISH marker sets.
 *
 *  The server store is a cache this client does not own: one process can be
 *  shared by several browsers and is emptied by a restart. The client keeps
 *  each set's SCM IDs and re-asserts them, so a set the server has forgotten
 *  (404) or that another session took over (409) heals transparently.
 *
 *  The store is passed in as ``FishStore`` rather than reached for directly,
 *  so this is testable without a Svelte component.
 */

import { ApiError } from './api/client'
import type { FishDensityResponse, FishSetResponse } from './api/types'

export type FishStore = {
  get: (label: string) => FishSetResponse | undefined
  /** Record a (re-)created set. */
  set: (label: string, resp: FishSetResponse) => void
  /** The SCM IDs this client created the set from, if still known. */
  ids: (label: string) => string[] | undefined
  /** Forget the set entirely (sets, visibility and IDs together). */
  drop: (label: string) => void
  /** Surface why a set disappeared. */
  report: (message: string) => void
}

export type FishApi = {
  create: (
    ids: string[],
    label: string,
    color: string,
    replace?: boolean,
  ) => Promise<FishSetResponse>
  density: (
    bins: number,
    labels: string[],
    signal?: AbortSignal,
  ) => Promise<FishDensityResponse>
}

function hasStatus(err: unknown, status: number): boolean {
  return err instanceof ApiError && err.status === status
}

/** Re-POST a set the server has forgotten, taking the label over. False when
 *  it cannot be restored, in which case the set is dropped so it stops
 *  erroring on every subsequent operation. */
export async function recreateFishSet(
  label: string,
  store: FishStore,
  api: FishApi,
): Promise<boolean> {
  const ids = store.ids(label)
  const existing = store.get(label)
  if (!ids || ids.length === 0 || !existing) {
    store.drop(label)
    store.report(
      `Marker set "${label}" is no longer on the server and could not be restored; it has been removed.`,
    )
    return false
  }
  try {
    store.set(label, await api.create(ids, label, existing.color, true))
    return true
  } catch (err) {
    store.drop(label)
    store.report(err instanceof Error ? err.message : String(err))
    return false
  }
}

/** Run an operation on a stored set, restoring the set and retrying once if
 *  the server no longer has it. */
export async function withFishRetry<T>(
  label: string,
  store: FishStore,
  api: FishApi,
  op: () => Promise<T>,
): Promise<T> {
  try {
    return await op()
  } catch (err) {
    if (!hasStatus(err, 404)) throw err
    if (!(await recreateFishSet(label, store, api))) throw err
    return await op()
  }
}

/** Create a set, taking the label over if another session on the same server
 *  already holds it (409) — this client's IDs are what it means by the label. */
export async function createFishSet(
  ids: string[],
  label: string,
  color: string,
  store: FishStore,
  api: FishApi,
): Promise<FishSetResponse> {
  let resp: FishSetResponse
  try {
    resp = await api.create(ids, label, color)
  } catch (err) {
    if (!hasStatus(err, 409)) throw err
    resp = await api.create(ids, label, color, true)
  }
  store.set(label, resp)
  return resp
}

/** Density for ``labels``, restoring any set the server reports as missing and
 *  retrying once, so one stale label never fails the whole preview. */
export async function fishDensityRecovering(
  bins: number,
  labels: string[],
  store: FishStore,
  api: FishApi,
  signal?: AbortSignal,
): Promise<FishDensityResponse> {
  const resp = await api.density(bins, labels, signal)
  if (resp.missing.length === 0) return resp
  let restored = false
  for (const label of resp.missing) {
    if (await recreateFishSet(label, store, api)) restored = true
  }
  const remaining = labels.filter((l) => store.get(l) !== undefined)
  if (!restored || remaining.length === 0) return resp
  return await api.density(bins, remaining, signal)
}
