/** Browser session ID for per-session FISH marker sets.
 *
 *  One `syntrack serve` process is shared by several browsers, so marker sets
 *  are namespaced by this ID (design: docs/design/FISH_SESSION_SCOPE.md). It
 *  is a namespace, not a credential: the server never interprets it and it
 *  grants nothing beyond seeing that namespace's sets.
 *
 *  Kept in `localStorage`, so reloads and reopened tabs keep their sets and
 *  all tabs of one browser agree. If storage is unavailable (private mode,
 *  blocked site data) we fall back to a per-page-load ID — sets then live
 *  only as long as the page, which is the old behaviour, not an error.
 */

export const SESSION_HEADER = 'X-SynTrack-Session'

const STORAGE_KEY = 'syntrack.session_id'

function newId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  // Older browsers: good enough for a namespace key.
  return `s-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

let cached: string | null = null

/** This browser's session ID, generated once and reused. */
export function sessionId(): string {
  if (cached !== null) return cached
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (stored && stored.trim()) {
      cached = stored
      return cached
    }
    const fresh = newId()
    window.localStorage.setItem(STORAGE_KEY, fresh)
    cached = fresh
    return cached
  } catch {
    // Storage blocked or unavailable — keep one ID for this page load.
    cached = newId()
    return cached
  }
}

/** Header to send with every request that touches session-scoped state. */
export function sessionHeaders(): Record<string, string> {
  return { [SESSION_HEADER]: sessionId() }
}

/** Test seam: forget the cached ID so the next call re-reads storage. */
export function resetSessionIdCache(): void {
  cached = null
}

/** Start a new session: mint a fresh ID and persist it, so subsequent requests
 *  land in an empty namespace. The caller is responsible for clearing the
 *  server's copy of the old session first (DELETE /api/fish) and for clearing
 *  local state — this only changes identity. Returns the new ID. */
export function newSessionId(): string {
  const fresh = newId()
  cached = fresh
  try {
    window.localStorage.setItem(STORAGE_KEY, fresh)
  } catch {
    // Storage blocked — the ID still holds for this page load.
  }
  return fresh
}
