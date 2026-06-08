# Running SynTrack in a container

Two formats are published on every `vX.Y.Z` release:

| Format | Where | Use when |
|---|---|---|
| Docker image | `ghcr.io/kavonrtep/syntrack:<tag>` on GHCR | Laptop / server / any box with Docker or Podman |
| SIF (Apptainer) | Release asset `syntrack-<tag>.sif` on GitHub | HPC cluster, no Docker daemon, no root |

Both are built from the same Dockerfile in CI (`.github/workflows/release.yml`).

## Docker (with compose)

### Prerequisites

- Docker ≥ 23 with the **Compose v2 plugin** (`docker compose`, space — not
  the legacy `docker-compose` v1 Python client, which is EOL and crashes on
  modern BuildKit-produced OCI manifests with `KeyError: 'ContainerConfig'`).
  On Debian/Ubuntu: `sudo apt install docker-compose-plugin`.
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

### Updating to a new release

Docker caches images locally, so `docker compose up` won't pull a newer
`:latest` on its own. Force a fresh pull first:

```bash
docker compose pull && docker compose up -d
```

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

## Input data format

SynTrack needs three things: a **config YAML**, a **genomes.csv** manifest, and
per-genome **.fai** + **.blast_out** files.

### genomes.csv

CSV with a header row. Columns:

| Column | Required | Description |
|---|---|---|
| `genome_id` | yes | Unique identifier for the genome |
| `fai` | yes | Path to the `.fai` index file |
| `SCM` | yes | Path to the BLAST `-outfmt 6` hits table |
| `label` | no | Friendly display name (defaults to `genome_id`) |

Paths are resolved **relative to the CSV file's directory** (unless absolute).
Row order determines the initial top-to-bottom display order.

```csv
genome_id,fai,SCM
genome_A,genome_A.fai,genome_A.blast_out
genome_B,genome_B.fai,genome_B.blast_out
```

### .fai — FASTA index

Standard `samtools faidx` output. Tab-separated, one row per sequence:

```
chr1    518136898    6          60    61
chr2    539960455    526772525  60    61
```

SynTrack uses only the first two columns (`name` and `length`); the rest
(byte offset, line bases, line width) are ignored.

### .blast_out — BLAST hits (SCM markers)

Standard BLAST `-outfmt 6` (tab-separated, no header). Each row is one hit
of a Single Copy Marker (SCM) against the genome assembly:

```
marker_001   chr1   99.0   45   0   0   1   45   1500234   1501892   1e-50   400
marker_002   chr3   97.8   43   1   0   1   43   891023    892501    5e-13   78
```

Key columns:

| Col | Name | SynTrack use |
|---|---|---|
| 0 | `qseqid` | **SCM ID** — must be consistent across all genomes |
| 1 | `sseqid` | Sequence name (must match `.fai`) |
| 2 | `pident` | Quality filter (`min_pident`) |
| 3 | `length` | Quality filter (`min_length`) |
| 8 | `sstart` | Genomic start position |
| 9 | `send` | Genomic end position |
| 10 | `evalue` | Quality filter (`max_evalue`) |
| 11 | `bitscore` | Uniqueness filter (best/second-best ratio) |

**Strand** is inferred from coordinates: `sstart < send` means `+`, otherwise
`-` (positions are swapped to canonical order internally).

**SCM IDs are opaque strings** — SynTrack never parses their format. The same
`qseqid` value in two genomes' BLAST tables means "same marker". Consistency
across genomes is the user's responsibility (typically ensured by BLASTing
every assembly against the same marker/probe set).

### Generating the BLAST table

```bash
# One shared marker set, BLASTed against each assembly:
blastn -query markers.fasta -subject genome_A.fasta \
       -outfmt 6 -num_alignments 1 -out genome_A.blast_out
```

The key requirement is that `markers.fasta` is **the same file** for every
genome so that `qseqid` values are consistent.

### syntrack_config.yaml (minimal)

```yaml
data:
  genomes_csv: ./genomes.csv     # path relative to this config file

blast_filtering:
  min_pident: 95.0
  min_length: 100                # lower for short probes (e.g. 30)
  max_evalue: 1.0e-10
  uniqueness_ratio: 1.5
```

See `syntrack_config.example.yaml` in the repo for all available options
(block detection, palette, rendering defaults, server settings).

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

**`KeyError: 'ContainerConfig'` on `docker-compose up`** — you're on the
legacy v1 client (`docker-compose`, hyphen). Install the Compose v2 plugin
(on Debian/Ubuntu: `sudo apt install docker-compose-v2`, or
`docker-compose-plugin` on older releases) and use `docker compose` (space).

**`PermissionError: [Errno 13]` opening `.fai` or `.blast_out`** — uid
mismatch. The image runs as uid 1001, but your genome files are probably
owned by your host user (uid 1000) without world-read. Uncomment the `user:`
line in `docker-compose.yml` and launch with
`UID=$(id -u) GID=$(id -g) docker compose up`, or hardcode `user: "1000:1000"`.

**Still `PermissionError` after setting `user:`, especially on a shared
filesystem** — Docker doesn't inherit your host user's supplementary groups
(Apptainer does — that's why Singularity "just works" in the same setup).
If access to the data is granted via a shared group or a POSIX ACL group
entry (`+` in `ls -l`, confirmed with `getfacl`), add those gids to compose:

```yaml
services:
  syntrack:
    user: "1000:1000"
    group_add:
      - "1009"     # gid of the shared group that unlocks the data
```

Check what you need with `id`, `getfacl <data-dir>`, and
`getent group <groupname>`.

**Non-root writes (Phase 4)** — future `.npz` cache support will want a
writable mount. Uncomment the `user:` line in compose and mount a
host-writable directory at `/cache`.
