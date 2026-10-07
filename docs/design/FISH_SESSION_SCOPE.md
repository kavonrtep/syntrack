# Session scoping for FISH marker sets

**Status:** implemented
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

The ID is generated once per browser (`crypto.randomUUID()`), kept in
`localStorage` so reloads and reopened tabs keep their sets, and never
interpreted by the server beyond being a dictionary key. No auth, no cookies, no CORS
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
| `DELETE /api/fish` | (did not exist) | drops this session's sets in one call |
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
- A session outlives the browser window (the ID is in `localStorage`), so sets
  reappear on the next visit. That is the point, but it needs an escape hatch:
  the "New session" action calls `DELETE /api/fish` and then mints a new ID, so
  the server's copy is freed before the browser stops being able to address it.
  Users reported the reappearance as a suspected bug, which is why the action
  exists and why the README states the lifetime explicitly.

## 3. Non-goals

- Authentication, user accounts, or per-user persistence. A session ID is not
  a login; anyone holding it sees those sets.
- Surviving a server restart. Sets remain in-memory; the Stage 1 client-side
  re-assertion remains the recovery path and is still needed.
- Scoping anything else per session. Genome data, pair caches and paint caches
  are read-only derived state and stay global — that is where the memory
  budget goes, and sharing them is the point.
- Separating tabs within one browser. The ID lives in `localStorage`, so all
  tabs of one browser share one session and therefore one set of marker sets.
  Two people sharing a desktop login also share sets; that is accepted, since
  a session ID is a namespace, not a credential.

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

Bounds (a shared process must not grow without limit). An index array is
`int32` per member SCM, so a 100k-SCM set costs 400 kB and set *counts* are a
poor proxy for memory. The authoritative cap is therefore on bytes:

- `MAX_FISH_BYTES = 128 MB` — total `nbytes` of all index arrays across all
  sessions. On overflow, whole sessions are evicted oldest-`last_seen` first
  until the new set fits. A single set larger than the cap is rejected with
  `413`, since evicting everything still would not make it fit.

  For that number to mean anything, the store must hold nothing else of size.
  It keeps metadata plus the index array and **not** the resolved positions:
  those measured ~111 MB for a 20-genome set at the 5000-positions-per-genome
  cap, against a 0.38 MB index — a 292× undercount that made the budget
  decorative and let a session of uploads reach gigabytes while reporting
  near-zero use. `GET /api/fish/{label}` re-resolves positions on demand.
  Measured after the change: 0.38 MB held per set, 0.38 MB accounted.
- `MAX_FISH_SETS = 512` per session, evicting least-recently-created — a cheap
  secondary guard, and the per-session pool removes the cross-session
  eviction thrash that the global pool had. It was 64, which silently evicted
  a user's earliest sets during a session spent uploading previously exported
  ones (reported from the field); bytes bind first at any realistic set size.
- `MAX_FISH_SESSIONS = 32`, evicting oldest `last_seen` first.
- `FISH_SESSION_TTL = 7 days` — sessions idle longer are dropped on the next
  request. Long on purpose: bytes are the real bound, and a short TTL expires
  a session under a tab that is still open (sets gone the next morning).

## 5. Failure modes

| Situation | Behaviour |
|---|---|
| Header absent (old client, curl) | `default` namespace — today's global behaviour, so no client is broken by the upgrade |
| Header present, session unknown | Treated as new and empty. The client re-asserts its sets (Stage 1 path) |
| Session evicted (TTL, byte cap) | Same as unknown: transparent re-assertion, one extra round trip — the client holds the SCM IDs of every set, including ones restored by hydration |
| Label collision within a session | Unchanged: 409 unless `replace: true` |
| Label used by *another* session | No longer visible; no collision, no takeover |
| Two tabs, same browser | Same session, same sets (`localStorage`) |
| Single set larger than `MAX_FISH_BYTES` | `413`, with the byte size in the detail; evicting other sessions would not help |

Logged on the `syntrack.fish` logger at INFO: session creation, set stored
(label, SCM count, index bytes, occupancy), set dropped with its cause,
session evicted or expired. At WARNING: a miss, an oversize set, and the
shared budget passing half. The store remembers its last 256 removals, so
`FishStore.miss_reason` can distinguish "removed 38s ago: set cap (512)" from
"this session never held that label"; that text goes into the 404 detail, so
a pasted error carries its own diagnosis. Session keys appear as an 8-character
prefix — enough to correlate one user's requests, without the full key.

The budget is reported to the client on create and list (`usage`), and shown
in the status bar while sets are uploaded.

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

## 7. Implementation notes

Implemented in `syntrack/api/fish_store.py` (`FishStore`, `FishSession`),
`syntrack/api/deps.py` (`get_session`), the five `/api/fish*` routes, and
`frontend/src/api/session.ts`. Deviations from the design above:

- **One extra endpoint: `GET /api/fish/{label}`.** §2 assumed the client could
  rebuild its sidebar from `GET /api/fish`, but that returns summaries without
  positions, which the overlay needs. The getter re-resolves the positions
  from the stored indices (the first cut returned a stored response; keeping
  those positions is what broke the byte budget, see §4). Output is identical
  to the create response, which a test asserts.
- **`413` for an oversize set**, as in §5, and additionally: when the caller's
  own session is the only one left, its oldest sets are shed before the request
  is refused. §4 only described evicting *other* sessions.
- **Hydration is guarded by a per-label revision counter.** It runs in the
  background while the user keeps working, so every write it makes is
  abandoned if that label changed in flight: writing stale IDs would make a
  later recovery resurrect the *previous* membership, and the failure path
  would delete a set the user had just re-imported. Both were found in review
  and are covered by regression tests.
- **Hydration also backfills each set's SCM IDs** (`GET /api/fish/{label}/scms`,
  in the background after the first render), so a restored set is as
  self-healing as one created in the page. The first cut skipped this, and a
  restored set then died on its first use after a restart — reported from the
  field and fixed. A set whose IDs cannot be fetched is dropped during
  hydration, while the reason can still be given, rather than left to fail
  later. Failure of hydration *itself* is silent — an empty sidebar is the
  pre-hydration behaviour, not an error.
- **A set that still cannot be restored raises `FishSetLostError`**, whose
  message names the set and says to re-import its SCM-ID file, instead of the
  stale `404` that triggered the recovery attempt.
- **Visibility is not restored.** Hydrated sets appear unticked, because which
  sets were visible is browser state the server never saw.

## 8. Decisions taken

- **Granularity: per browser** (`localStorage`), not per tab. A reopened tab
  inherits the user's sets, and all tabs of one browser agree. Decided
  2026-10-05.
- **Bound: total bytes, 128 MB** across all sessions (§4), rather than set
  counts alone, which understate memory by an order of magnitude. Decided
  2026-10-05.
- **No `GET /api/fish?all=true`.** Operationally handy for debugging a shared
  instance, but it would expose other sessions' labels. DEBUG logs carry the
  same information for whoever runs the server.
