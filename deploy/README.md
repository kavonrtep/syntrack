# Running SynTrack in a container

Two formats are published on every `vX.Y.Z` release:

| Format | Where | Use when |
|---|---|---|
| Docker image | `ghcr.io/kavonrtep/syntrack:<tag>` on GHCR | Laptop / server / any box with Docker or Podman |
| SIF (Apptainer) | Release asset `syntrack-<tag>.sif` on GitHub | HPC cluster, no Docker daemon, no root |

Both are built from the same Dockerfile in CI (`.github/workflows/release.yml`).

## Docker (with compose)

### Prerequisites

- Docker ≥ 23 (or Podman with Compose plugin).
- A `syntrack_config.yaml` — start from `syntrack_config.example.yaml` in the
  repo (or attached to each GitHub Release).
- Your genome data on a path the container can mount.

### One-time setup

```bash
# Grab the compose template and an example config into your working dir.
mkdir syntrack-run && cd syntrack-run
curl -LO https://raw.githubusercontent.com/kavonrtep/syntrack/main/deploy/docker-compose.yml
curl -LO https://raw.githubusercontent.com/kavonrtep/syntrack/main/syntrack_config.example.yaml
mv syntrack_config.example.yaml syntrack_config.yaml
```

Edit `syntrack_config.yaml` to point at your `genomes.csv`, then edit
`docker-compose.yml` to add one `host_path:host_path:ro` volume per top-level
directory referenced by that CSV (see below).

### The matching-host-path mount convention

The image treats `genomes.csv` paths as-is — **no rewriting**. The convention
is that every mount bind is **identical on both sides of the colon**:

```yaml
volumes:
  - /mnt/ceph/454_data/Pisum_pangenome/assemblies:/mnt/ceph/454_data/Pisum_pangenome/assemblies:ro
  - /scratch/my_genomes:/scratch/my_genomes:ro
```

Why this layout:

1. Absolute paths in `genomes.csv` work unchanged inside and outside the
   container — you use the same CSV on bare metal and in compose.
2. Symlinks created by tools like `example_data/link_data.sh` (which resolve
   to `/mnt/ceph/...`) keep resolving correctly inside the container, because
   those paths exist there too.
3. No invented `/data/...` paths to translate. What the CSV says is what it
   gets.

If the data tree contains symlinks that point **outside** the mounted
directories, add those target trees as extra mounts (same pattern).

### Run

```bash
docker compose up          # foreground, Ctrl-C to stop
docker compose up -d       # detached
docker compose logs -f     # watch logs
docker compose down        # stop + remove
```

Then open http://localhost:8765 in a browser.

### Remote server (SSH tunnel)

When you run compose on a remote host, forward the port to your laptop:

```bash
ssh -L 8765:localhost:8765 <remote-host>
# then on the remote:
docker compose up -d
# and on your laptop, open http://localhost:8765
```

The container binds `0.0.0.0:8765` internally, so the published port is
reachable from the host; SSH takes it the rest of the way to your browser.

### Plain `docker run` (if you prefer)

```bash
docker run --rm -it \
  -p 8765:8765 \
  -v "$PWD/syntrack_config.yaml":/config/syntrack_config.yaml:ro \
  -v /mnt/ceph/454_data:/mnt/ceph/454_data:ro \
  ghcr.io/kavonrtep/syntrack:latest
```

## Apptainer / Singularity (HPC)

Grab the prebuilt SIF from the release page or build it yourself from the
Docker image:

```bash
# prebuilt:
wget https://github.com/kavonrtep/syntrack/releases/download/v0.2.0/syntrack-v0.2.0.sif

# or rebuild locally:
apptainer build syntrack-v0.2.0.sif docker://ghcr.io/kavonrtep/syntrack:v0.2.0
```

Run on a compute node (Apptainer auto-binds `$HOME` and `$PWD`, so things
under your scratch or home directory are usually visible without extra
`--bind` flags):

```bash
apptainer run \
  --bind /mnt/ceph/454_data/Pisum_pangenome/assemblies:/mnt/ceph/454_data/Pisum_pangenome/assemblies:ro \
  --env SYNTRACK_CONFIG=$PWD/syntrack_config.yaml \
  syntrack-v0.2.0.sif
```

Apptainer uses the host network by default, so the server binds
`0.0.0.0:8765` and you reach it with the usual SSH port-forward:

```bash
# from your laptop:
ssh -L 8765:<compute-node>:8765 <login-node>
# open http://localhost:8765
```

## Environment variables (image defaults)

| Variable | Default in image | What it does |
|---|---|---|
| `SYNTRACK_CONFIG` | `/config/syntrack_config.yaml` | Path to the YAML config. Override via `-e` or `--config`. |
| `SYNTRACK_HOST` | `0.0.0.0` | Bind address. Inside a container always `0.0.0.0`. |
| `SYNTRACK_PORT` | `8765` | Bind port. Publish it with `-p` on the host. |
| `SYNTRACK_FRONTEND_DIR` | `/app/frontend/dist` | Directory served at `/`. Leave alone. |

All four can be overridden via `docker run -e` or compose `environment:`;
command-line flags (e.g. `syntrack serve --port 9000`) win over env.

## Troubleshooting

**"no config provided"** — your `syntrack_config.yaml` isn't at
`/config/syntrack_config.yaml` inside the container. Check the volume path.

**"fai not found for …"** — a path in `genomes.csv` isn't visible. Either
the directory isn't mounted, or a symlink target lies outside all your
mounts. Add the missing path as another `host_path:host_path:ro` volume.

**Slow first startup** — loading 8 pea genomes takes ~30–60 s. Compose's
healthcheck waits up to 90 s before reporting the container as healthy.
If you see `starting` for the first minute, that's normal.

**Port already in use on host** — change the left side of the `ports:`
mapping to a free port, e.g. `"9000:8765"`.

**Non-root writes (Phase 4)** — future `.npz` cache support will want a
writable mount. Uncomment the `user:` line in compose and mount a
host-writable directory at `/cache`.
