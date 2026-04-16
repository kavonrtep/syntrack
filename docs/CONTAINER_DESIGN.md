# SynTrack — Container shipping design (draft v0.1)

**Status:** proposal for review. No code changes yet. Source of truth for subsequent
work: once this doc is approved, the code prep (§4), the Dockerfile (§5), the
compose file (§7.1), and the CI workflow (§8) all get written directly from it.

---

## 1. Goals / non-goals

### In scope

- **One authoritative image**, built in GitHub Actions on every release tag, pushed to
  GitHub Container Registry (`ghcr.io/<owner>/syntrack:<tag>`).
- **A Singularity / Apptainer `.sif`** file attached to the same GitHub Release,
  produced by converting the published Docker image in the same CI run.
- **A `docker-compose.yml` template** shipped in the repo that the user edits to point
  at their data directories and the config YAML.
- **A container suitable for both a laptop and a remote server.** The app binds on
  `0.0.0.0:<port>` so that, from inside the container, `http://<server>:<port>`
  works for either localhost or a port-forwarded SSH tunnel.
- **Scattered input data supported** via multiple bind mounts — the user isn't forced
  to flatten their genome folders into a single directory.
- **URL printed to stdout at startup.** No browser auto-launch (there's no browser in
  the container, and the user may be on a remote box anyway).
- **Non-root runtime.** Image ships with a dedicated unprivileged user.

### Out of scope (at least for v0.2.0)

- Windows-native containers. Linux/amd64 only initially; arm64 optional later if
  anyone asks.
- Auto-update / self-update inside the container.
- GUI wrapper, tray icon, AppImage, conda / nix / pip packaging. Docker + SIF only.
- Database, multi-user auth, HTTPS termination. Out of scope for the app itself; if
  deployed on a shared server, put it behind a reverse proxy separately.
- Persistent caching between container runs. v0.1 is in-memory only; when Phase 4
  ships the `.npz` pair cache, we revisit (§12).

---

## 2. Deployment contexts

Three scenarios the image must handle without special-casing. Each user lands in one.

| | Context A — laptop | Context B — remote server | Context C — HPC cluster |
|---|---|---|---|
| Invocation | `docker compose up` | `docker compose up` on the server over SSH | `singularity run ...sif` on a compute node |
| Browser on | laptop | laptop | laptop (tunnelled) |
| Port reach | `localhost:8765` | `ssh -L 8765:localhost:8765 server` | `ssh -L 8765:<node>:8765 loginnode` |
| Data location | under laptop's `$HOME` | under server's `$HOME` | `/scratch/<user>` + `$HOME` |
| Writable cache (Phase 4) | `./cache` in project | same | `$SCRATCH/cache` |

The image binds `0.0.0.0:<port>` regardless, so port forwarding Just Works in all three
— URL printed to stdout is a `localhost` URL, which is correct when forwarded.

---

## 3. Inputs and outputs

### Input the user supplies (every run)

- **Config YAML** (`syntrack_config.yaml`): points at the genomes manifest CSV, block
  detection / blast filtering params, palette. Same format as today.
- **Genomes manifest CSV** (`genomes.csv`): columns `genome_id,fai,SCM[,label]`. FAI and
  BLAST paths in the CSV can be *absolute paths as visible inside the container*.
- **FAI + BLAST tables** for every genome. These can live in multiple directories;
  we allow multiple volume mounts.

### Outputs

- **Stdout log**, including a single line:
  `SynTrack listening on http://0.0.0.0:8765 — open http://localhost:8765 in a browser (SSH-forward if remote).`
- **HTTP server** on the configured port.
- **(Later, Phase 4)** `.npz` pair cache files under a writable mount.

---

## 4. Code changes required before packaging

Nothing drastic, but needed before a useful image can exist. Landed in their own
commit(s) before the Dockerfile.

### 4.1 CLI — `--host` and `--port` flags on `syntrack serve`

Today those values come exclusively from the YAML (`server.host`, `server.port`). In a
container we want the image's `CMD` to set `--host 0.0.0.0` regardless of what the
user's YAML says, because:

- The user's YAML is their own, shared between bare-metal and container runs — they
  shouldn't have to edit it to switch.
- `127.0.0.1` inside a container is useless: the published port doesn't reach it.

Proposed semantics: CLI flag > YAML > default. One-liner change in `syntrack/cli.py`.

### 4.2 CLI — `--config` default from env var

Add `SYNTRACK_CONFIG` env var as a fallback for `--config`. The Dockerfile sets this
to `/config/syntrack_config.yaml`, so `docker run ... syntrack serve` works with no
explicit flag as long as the user bind-mounts their config there.

### 4.3 FastAPI — serve the built frontend at `/`

Today the API is mounted under `/api/*` and Vite serves the UI in dev. For a packaged
build, FastAPI needs to serve `frontend/dist/*` as static under `/`:

```python
app.mount("/", StaticFiles(directory=DIST_DIR, html=True), name="ui")
```

Order matters: API routers mounted before the static mount so `/api/*` takes precedence.

A `SYNTRACK_FRONTEND_DIR` env var lets the image point at `/app/frontend/dist`. During
dev it stays unset and no static mount happens (Vite handles the UI at `:5173`).

### 4.4 Startup log line

Dedicated log line printed *after* the app finishes loading genomes, including an
explicit "SSH-forward if remote" hint. Current line is close but slightly cramped and
prints *before* the ~30 s load (makes it look like the server is up when it isn't
yet serving requests). Move it after SCMStore.load returns.

### 4.5 `/api/healthz`

Tiny endpoint returning `{ "status": "ok", "genomes": N, "universe": M }` so Compose
can declare a healthcheck. Also a useful smoke check for users.

### 4.6 (Optional) Read-only-safe file I/O

Make sure `syntrack serve` doesn't create files in the project root or under
`$HOME` by accident. Currently it doesn't — only reads are performed — but we should
confirm once Phase 4 cache lands.

Nothing above is a big diff; all of §4 is roughly one commit's worth of code.

---

## 5. Docker image design

### 5.1 Layer structure

Multi-stage Dockerfile, three stages:

```dockerfile
# 1) Build the Svelte/Vite frontend.
FROM node:22-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build   # produces /app/frontend/dist

# 2) Resolve Python deps with uv into an isolated venv.
FROM python:3.12-slim-bookworm AS python-build
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock ./
COPY syntrack/ syntrack/
RUN uv venv /opt/venv
RUN uv pip install --no-cache --python /opt/venv/bin/python -e .

# 3) Runtime.
FROM python:3.12-slim-bookworm
RUN groupadd -r syntrack && useradd -r -g syntrack -m -d /home/syntrack syntrack
COPY --from=python-build /opt/venv /opt/venv
COPY --from=python-build /app/syntrack /app/syntrack
COPY pyproject.toml /app/pyproject.toml
COPY --from=frontend-build /app/frontend/dist /app/frontend/dist
ENV PATH="/opt/venv/bin:$PATH" \
    SYNTRACK_CONFIG=/config/syntrack_config.yaml \
    SYNTRACK_FRONTEND_DIR=/app/frontend/dist \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
EXPOSE 8765
USER syntrack
WORKDIR /app
ENTRYPOINT ["syntrack"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8765"]
```

Rationale:

- **Three stages** — frontend build artifacts and Python build artifacts both excluded
  from the final image; node, npm, uv, apt caches all left behind.
- **`python:3.12-slim-bookworm`** — slim is small, bookworm is current stable Debian.
  Polars wheels ship linked against glibc and manylinux_2_28; bookworm satisfies.
  Avoid Alpine: musl and polars wheels don't mix.
- **Editable install (`-e .`)** keeps the image surface predictable without having to
  build a wheel. Alternative: `uv pip install .` (non-editable) — we'll pick whichever
  turns out smaller.
- **Non-root user** (`syntrack`, UID/GID from system range). The user writes to nothing
  inside the image today; future `.npz` cache gets a mount (§6.3).
- **`SYNTRACK_CONFIG` / `SYNTRACK_FRONTEND_DIR`** default env vars mean the default
  CMD works without any argument editing as long as the user mounts `/config/...`.

### 5.2 Size target

- Python 3.12-slim base: ~120 MB.
- numpy + polars + fastapi + uvicorn + pydantic + rest: ~180–220 MB.
- Frontend bundle: ~1 MB.
- Our source code: ~1 MB.
- Total compressed image: **~270–350 MB** expected. Uncompressed ~500 MB. Acceptable.

### 5.3 Runtime user / permissions

- Run as user `syntrack` (UID selected from the system range, e.g. 999).
- Document `user:` in compose so host-UID users can be mapped if they need to write
  (Phase 4 cache).
- Everything under `/app` is owned by root in the image; `syntrack` user has read-only.
- `/config` and `/data` mount points are created in the image with `chown syntrack`
  so bind-mount permissions are predictable.

---

## 6. Runtime behaviour

### 6.1 Port binding

- Default: `--host 0.0.0.0 --port 8765`.
- User overrides port by setting `SYNTRACK_PORT` env or by editing the CMD in
  compose. Host-side published port is separate (handled by `ports:` in compose).

### 6.2 Static file serving

FastAPI mounts `/app/frontend/dist/` at `/` using `StaticFiles(html=True)`. Routes:

- `GET /` → `index.html`
- `GET /assets/*.{js,css,map}` → static files
- `GET /api/*` → JSON API (unchanged)
- `GET /healthz` → health JSON (new, §4.5)

### 6.3 Mounts — the "scattered data" story

The user's genome folders can live anywhere on the host. Two conventions:

1. **Config lives at `/config/syntrack_config.yaml`** (a single-file bind mount).
2. **Data directories mount under `/data/...`** — one mount per top-level directory
   the user's genomes.csv refers to. The user edits paths in `genomes.csv` to reflect
   the in-container locations (e.g., `/data/ji1006/chr1.fai`).

The manifest parser already resolves relative paths against the `genomes.csv`
directory, so if the user bind-mounts one directory that contains both `genomes.csv`
and its neighbouring FAI/BLAST files, relative paths still work. For scattered
setups they write absolute paths in the CSV matching the container-side mount points.

Future `.npz` pair cache (Phase 4) → mount a writable directory at `/cache` and set
`SYNTRACK_CACHE_DIR` env.

### 6.4 Logging

- uvicorn logs to stdout by default. Kept.
- `syntrack serve` prints a single banner line after SCMStore.load returns:

```
SynTrack v0.1.3 listening on http://0.0.0.0:8765
  Open http://localhost:8765 in a browser.
  Remote? Forward the port first: ssh -L 8765:<this-host>:8765 <this-host>
```

### 6.5 Health check

`/healthz` returns HTTP 200 as soon as SCMStore has loaded. Compose `healthcheck:`
polls every 30 s with a 5 s start grace × startup period, so the container isn't
reported healthy until the first load completes (which may take ~30 s on 8 pea
genomes). Kubernetes / remote orchestrators get the same signal for free.

---

## 7. User surfaces

### 7.1 `docker-compose.yml` template (shipped in the repo)

```yaml
# syntrack/docker-compose.yml — copy to your host, edit paths, then:
#   docker compose up
services:
  syntrack:
    image: ghcr.io/<owner>/syntrack:latest
    ports:
      - "8765:8765"
    volumes:
      # Your config file. Paths inside it must be /data/... (see below).
      - ./syntrack_config.yaml:/config/syntrack_config.yaml:ro
      # Your data directories. One mount per directory you want visible.
      # The three below are examples — add or remove as you have.
      - /mnt/ceph/454_data/.../genomes.csv:/data/genomes.csv:ro
      - /mnt/ceph/454_data/.../JI1006_2026-01-19:/data/JI1006_2026-01-19:ro
      - /mnt/ceph/454_data/.../JI15_2026-01-19:/data/JI15_2026-01-19:ro
    # Uncomment if you need to match your host UID (e.g. to write a cache):
    # user: "${UID:-1000}:${GID:-1000}"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8765/healthz').status == 200 else 1)"]
      interval: 30s
      timeout: 5s
      start_period: 90s  # accommodates the ~30-60s SCM load
      retries: 3
```

### 7.2 Plain `docker run` (for readme / reference)

```bash
docker run --rm -it \
  -p 8765:8765 \
  -v /path/to/syntrack_config.yaml:/config/syntrack_config.yaml:ro \
  -v /path/to/data:/data:ro \
  ghcr.io/<owner>/syntrack:v0.1.3
```

### 7.3 Singularity / Apptainer

```bash
# build from the published docker image, once
singularity build syntrack.sif docker://ghcr.io/<owner>/syntrack:v0.1.3

# run (Singularity auto-binds $HOME and $PWD, so data under $HOME is visible)
singularity run \
  --bind /mnt/ceph/454_data/.../JI1006_2026-01-19:/data/JI1006_2026-01-19:ro \
  --bind /path/to/syntrack_config.yaml:/config/syntrack_config.yaml:ro \
  syntrack.sif
```

We also publish a prebuilt `.sif` as a Release asset (§8.3), so users can skip the
build step and just `wget`.

---

## 8. Build pipeline — GitHub Actions

### 8.1 On every push to `main`

`.github/workflows/ci.yml` (already needed for tests anyway):

- `backend-tests` job: pytest, ruff, mypy on the sandbox-equivalent Python image.
- `frontend-tests` job: `npm ci && npm test && npm run check && npm run build`.
- `image-smoke` job: **build** the Docker image on each PR (don't push), run
  `docker run <image> --help` as a smoke test. Catches Dockerfile regressions
  before the image ever lands in a release.

### 8.2 On tag `v*` (e.g. `v0.2.0`)

`.github/workflows/release.yml`:

1. **Build & push Docker image** to `ghcr.io/<owner>/syntrack` with tags
   `v0.2.0` and `latest`. Uses `docker/build-push-action@v6` + `docker/metadata-action@v5`.
   Label metadata via OCI spec (source, version, revision).
2. **Convert to SIF.** Install Apptainer in the runner (`apptainer/setup-apptainer`),
   run `apptainer build syntrack-v0.2.0.sif docker://ghcr.io/<owner>/syntrack:v0.2.0`.
3. **GitHub Release.** Create (or update) the release for the tag, attach:
   - `syntrack-v0.2.0.sif` (a couple of hundred MB; GH Releases allow 2 GB)
   - `syntrack-v0.2.0.sha256` (sha256 sum of the sif)
   - `docker-compose.yml` (the template from §7.1)
   - `syntrack_config.example.yaml`

### 8.3 Secrets / permissions

- `GITHUB_TOKEN` for GHCR push; the workflow declares `permissions: packages: write`.
- No other secrets required. SIF push to sylabs.io optional later; for now the
  Release asset is the distribution channel.

### 8.4 Multi-arch

Start amd64-only. Adding arm64 later is a one-line change in
`docker/build-push-action` (`platforms: linux/amd64,linux/arm64`). Numpy / polars ship
arm64 wheels now, so this is cheap once demand exists.

---

## 9. Tag & versioning strategy

- **Source of truth for version:** git tag. Every tag `vX.Y.Z` triggers the release
  workflow; the image tag matches.
- **`:latest`** points at the most recent non-pre-release tag.
- **`:main`** (optional, on every push to main) for people who want bleeding-edge —
  not advertised in the README until we're confident about main's stability.
- **Pre-release tags** (`v0.2.0-rc1`) push only to their own tag (no `:latest` update,
  no SIF-to-Release attachment unless explicitly requested).
- `pyproject.toml` version bumped in the tagging commit; CI asserts the tag matches
  (prevents mismatched images).
- Version number jumps to **v0.2.0** when containers first ship — we've been on
  v0.1.x; container distribution is a breaking change in deployment shape.

---

## 10. Size, startup, resource expectations

| | Expected |
|---|---|
| Compressed image size | 270 – 350 MB |
| Uncompressed image size | 450 – 550 MB |
| SIF size | similar (compressed squashfs) |
| Cold startup — small dataset (tests/fixtures) | < 2 s |
| Cold startup — 8 pea genomes (~950 K BLAST rows each) | ~30 – 60 s |
| Warm startup (Phase 4 `.npz` cache) | < 5 s (future) |
| Peak memory — 8 pea genomes | ~1.5 – 2 GB |
| Idle memory after load | ~1 GB |

These are rough; we'll measure on the first build and tighten the numbers in the
README.

---

## 11. Security & hardening

Deliberately minimal for a single-user dev tool, but:

- Runs as unprivileged user `syntrack` by default.
- No shell in the default CMD; entrypoint is `syntrack` (a Python CLI).
- No writes to the image filesystem; everything user-writable lives on bind mounts.
- `HEALTHCHECK` uses stdlib urllib (no extra deps).
- No inbound auth — the app was never designed for it. If the user deploys on a
  multi-tenant server, they put it behind a reverse proxy with auth (documented,
  not bundled).
- No outgoing network requests at runtime.
- Image scanning: run `trivy` in CI; fail the release build on `HIGH`/`CRITICAL`
  CVEs unless we explicitly accept them.

---

## 12. Future work (v0.2.x / Phase 4)

- **`.npz` pair cache** needs a writable mount (`/cache`). Once landed, the compose
  template grows a `- ./cache:/cache:rw` volume and `user:` becomes recommended.
- **`syntrack precompute` CLI** runs inside the container with the cache volume
  mounted, populates `.npz` files, then exits. Makes the first `syntrack serve`
  fast on the real dataset.
- **arm64** if any user asks.
- **Prebuilt image for the example pea dataset** (with the public-ish subset of
  FAI/BLAST baked in) — possibly, only if there's a clear pedagogical case.

---

## 13. Open questions

A few things we haven't pinned and I want your call on before I start writing code:

1. **Registry.** GHCR under the repo owner's name, fine? Any preference for
   public-vs-private? (Public assumed.)
2. **Version bump.** Next tag becomes **v0.2.0** (container shipping as the headline
   feature), or keep in v0.1 and add v0.1.4?
3. **Compose file location.** Ship `docker-compose.yml` in the repo root, or under
   `deploy/` to keep the top level clean? I'd suggest `deploy/docker-compose.yml`.
4. **Build target for first release.** amd64-only, OK?
5. **Apptainer vs Singularity CE.** Assume Apptainer (community fork, default on
   most new HPC installs) for the CI convert step. Users running Sylabs Singularity
   CE can still run the resulting SIF.
6. **Frontend `npm ci` in CI.** We don't yet commit `package-lock.json` (we do —
   verified). CI will use it. OK as-is.
7. **`syntrack serve --config` default coming from env.** Acceptable to drop the
   `--config` required flag when `SYNTRACK_CONFIG` is set? (Currently required in
   Typer.) Reasonable — makes the image command line clean.
8. **Stable config path convention.** `/config/syntrack_config.yaml` as a single-file
   mount, `/data/...` for bind-mounted genome directories. Any concerns?
9. **Image name.** `ghcr.io/<owner>/syntrack` — needs your GH handle / org. Placeholder
   above as `<owner>`.

---

## Appendix A — files we'd add / change after approval

Nothing here exists yet; this is the list that drops once the plan is signed off.

```
<repo>/
├── Dockerfile                               # §5
├── .dockerignore                            # standard
├── deploy/
│   ├── docker-compose.yml                   # §7.1
│   ├── compose.override.example.yml         # optional overrides (cache mount, etc.)
│   └── README.md                            # short how-to (copy → edit → up)
├── .github/workflows/
│   ├── ci.yml                               # §8.1 (or extend existing)
│   └── release.yml                          # §8.2
├── syntrack/
│   ├── cli.py                               # §4.1 --host / --port / env default
│   └── api/app.py                           # §4.3 StaticFiles mount; §4.5 /healthz
├── docs/
│   └── CONTAINER_DESIGN.md                  # this file (drop "draft" label on merge)
└── README.md                                # "Run via Docker" + "Run via Singularity"
```

No changes needed in `syntrack_config.example.yaml`. No new Python deps.
