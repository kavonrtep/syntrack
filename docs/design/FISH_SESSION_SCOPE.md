# Session scoping for FISH marker sets

**Status:** proposed
**Author:** Petr Novák
**Date:** 2026-10-05
**Relates to:** `DESIGN_v03.md` §2.1 (deployment assumptions), §F4 (FISH
painting), `POST /api/fish`

## 1. Problem

`DESIGN_v03.md` §2.1 assumes "single-user local deployment". Instances are in
fact deployed shared: several people point their browsers at one `syntrack
serve` process. FISH marker sets live in that process (`AppState.fish_sets`,
keyed by label), so the label namespace is global to the server:

- Two users who highlight the same region of the same genome derive the same
  label. Either collides with the other (`409`), or — after the Stage 1 fix
  below — silently takes it over.
- A user importing `pair_1_...tsv` overwrites a different set that another
  user imported under the same filename.
- One user deleting a set removes it from under another user.
- The sidebar of each browser shows only the sets that browser created, so the
  server state and every client's view disagree in both directions.

Stage 1 (client-side re-assertion, already implemented) made this *coherent*
rather than correct: the client keeps
each set's SCM IDs and re-asserts them, so a lost or stolen set is restored
transparently and errors stop reaching users. Collisions are harmless when the
label implies the content (region + genome), but not for imported files, where
two users can mean different SCM sets by the same filename. Churn also grows
with the number of users: each re-assertion re-resolves the set server-side.

This document proposes making sets private to a session, which is what both
users and the code already assume.

## 2. Interface

A session is identified by an opaque client-generated ID sent as a header on
every `/api/fish*` request:

```
X-SynTrack-Session: 5f2c1e9a8b3d4c7e
```

The ID is generated once per browser tab (`crypto.randomUUID()`), kept in
`sessionStorage` so a reload keeps its sets, and never interpreted by the
server beyond being a dictionary key. No auth, no cookies, no CORS
complications — it is a namespace, not a credential.

```python
# syntrack/api/deps.py
def get_session(
    x_syntrack_session: Annotated[str | None, Header()] = None,
) -> str:
    """Session key for per-session state. Absent header -> the shared
    'default' namespace, so an old client keeps working unchanged."""
```

Endpoint contracts are unchanged. What changes is which store they see:

| Endpoint | Before | After |
|---|---|---|
| `POST /api/fish` | one global dict | this session's dict |
| `GET /api/fish` | every set on the server | this session's sets |
| `DELETE /api/fish/{label}` | any set | this session's set only (404 otherwise) |
| `POST /api/fish/density` | any label | this session's labels |
| `GET /api/fish/{label}/scms` | any label | this session's label only |

Consequences worth stating explicitly:

- `GET /api/fish` becomes meaningful for the client to hydrate from on mount,
  which Stage 1 deliberately did not do (it would have listed other users'
  sets). After this change, hydration is correct and removes most of the
  re-assertion churn.
- Sets are no longer shared between users. Sharing happens by exchanging the
  exported SCM-ID file, which already round-trips (`↓ SCM IDs` → file import).

## 3. Non-goals

- Authentication, user accounts, or per-user persistence. A session ID is not
  a login; anyone holding it sees those sets.
- Surviving a server restart. Sets remain in-memory; the Stage 1 client-side
  re-assertion remains the recovery path and is still needed.
- Scoping anything else per session. Genome data, pair caches and paint caches
  are read-only derived state and stay global — that is where the memory
  budget goes, and sharing them is the point.
- Cross-tab sharing within one browser. Each tab is its own session; two tabs
  of the same user do not see each other's sets.

## 4. Data structures

`AppState` gains one level of indirection, replacing the two flat dicts:

```python
@dataclass(slots=True)
class FishSession:
    """One browser session's marker sets. Capped; LRU by last access."""
    sets: dict[str, FishSetResponse] = field(default_factory=dict)
    indices: dict[str, np.ndarray] = field(default_factory=dict)
    last_seen: float = 0.0          # monotonic clock, for eviction


@dataclass(slots=True)
class AppState:
    ...
    fish_sessions: dict[str, FishSession] = field(default_factory=dict)
```

Bounds (a shared process must not grow without limit):

- `MAX_FISH_SESSIONS = 32` — on overflow, evict the session with the oldest
  `last_seen`.
- `MAX_FISH_SETS = 64` per session, evicting least-recently-created, as now.
- `FISH_SESSION_TTL = 12 h` — sessions idle longer than this are dropped on
  the next request.

Memory: an index array is `int32` per member SCM, so a 100k-SCM set costs
400 kB. The worst case under these caps is 32 × 64 × 400 kB ≈ 800 MB, which
would blow the ~1.3 GB budget in `CLAUDE.md`. Therefore the cap is on total
bytes, not set count: `MAX_FISH_BYTES = 128 MB` summed across all sessions,
evicting oldest-session-first until it fits. Set and session counts stay as
cheap secondary guards.

## 5. Failure modes

| Situation | Behaviour |
|---|---|
| Header absent (old client, curl) | `default` namespace — today's global behaviour, so no client is broken by the upgrade |
| Header present, session unknown | Treated as new and empty. The client re-asserts its sets (Stage 1 path) |
| Session evicted (TTL, byte cap) | Same as unknown: transparent re-assertion, one extra round trip |
| Label collision within a session | Unchanged: 409 unless `replace: true` |
| Label used by *another* session | No longer visible; no collision, no takeover |
| Two tabs, same user | Separate sets. A set created in one tab is not listed in the other — accepted (see non-goals) |

Logged at DEBUG: session creation, eviction (with reason and freed bytes),
and re-assertion of an unknown label. Nothing is logged per request.

## 6. Test strategy

Smallest assertions that prove it works:

1. Two `TestClient` requests with different `X-SynTrack-Session` values create
   the same label; both succeed with 201, `GET /api/fish` returns one set for
   each, and `GET /api/fish/{label}/scms` returns each session's own SCM IDs.
2. A `DELETE` from session B does not remove session A's identically-labelled
   set.
3. `POST /api/fish/density` from session B reports a label created by session A
   in `missing`, not in `sets`.
4. No header behaves exactly as the current global store (regression guard for
   old clients and for the CLI).
5. Byte-cap eviction: creating sets past `MAX_FISH_BYTES` evicts the oldest
   session, and the evicted session's next request re-creates its set.
6. TTL eviction with a monkeypatched clock.

Frontend: the session ID is generated once, reused across requests within a
tab, persists across a reload, and differs between tabs — unit-testable as a
helper module (`frontend/src/api/session.ts`), separate from `App.svelte`.

## 7. Open questions

- Is per-tab the right granularity, or per browser (`localStorage`), so a
  reopened tab inherits the user's sets? Per-browser is friendlier; per-tab is
  stricter about two people on one machine. Recommend `localStorage` with a
  per-browser ID, which also removes the two-tab surprise above.
- Should `GET /api/fish` gain an `?all=true` for debugging a shared instance?
  Useful operationally, but it exposes other sessions' labels. Recommend
  leaving it out and relying on DEBUG logs.
