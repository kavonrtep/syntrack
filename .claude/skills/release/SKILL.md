---
name: release
description: Cut a SynTrack release — bump the version in BOTH pyproject.toml and syntrack/__init__.py, run the full test suite, commit, and tag. Use when the user asks to "cut a release", "make a release", "bump the version", or "tag" a version. Prevents the two-file version drift that has happened before.
---

# Release a new SynTrack version

The version lives in **two files** that must stay in sync — this is the whole
point of the skill, because they have drifted before (pyproject bumped, but
`__version__` left stale, which breaks `/healthz`, the CLI, and the diskcache
manifest hash):

- `pyproject.toml` → `version = "X.Y.Z"`
- `syntrack/__init__.py` → `__version__ = "X.Y.Z"`

## Inputs

The target version `X.Y.Z` (semver). If the user didn't give one, infer the
bump from the work since the last tag and confirm with the user before tagging
(patch for fixes/perf, minor for new user-facing features). Don't invent a
version silently.

## Steps

1. **Preflight.** Run `git status` — the working tree should be clean (or only
   contain the changes being released). `git tag -l "v*"` and
   `git log --oneline $(git describe --tags --abbrev=0 2>/dev/null)..HEAD` to
   see what's shipping and confirm the version number.
2. **Bump both files** to `X.Y.Z` (edit `pyproject.toml` and
   `syntrack/__init__.py`). They MUST match.
3. **Verify the runtime version:**
   `./dev.sh python -c "from syntrack import __version__; print(__version__)"`
   must print `X.Y.Z`.
4. **Full verification (not the fast inner loop):**
   - `./dev.sh pytest` (full suite, including integration)
   - `cd frontend && npm run check && npm test && npm run build`
   - All must pass. If anything fails, stop and report — do not tag.
5. **Commit** with a `release:` prefix and a short summary of what's new since
   the last tag:
   `git commit -m "release: bump version to X.Y.Z" -m "<summary>"`
   Include the standard `Co-Authored-By:` trailer.
6. **Tag** lightweight, matching the existing convention:
   `git tag vX.Y.Z`. (Existing tags are lightweight — `git cat-file -t vLAST`
   returns `commit`. Don't switch to annotated tags.)
7. **Hand off.** Do NOT push (the user pushes). Tell them the exact commands:
   `git push origin main && git push origin vX.Y.Z`. If SSH/remote is
   unreachable from the sandbox, say so and note you couldn't verify whether
   prior tags are already pushed.

## Notes

- Frontend cannot be browser-verified in this environment — if the release
  includes visual changes, flag that they're unverified and suggest the user
  eyeball them before pushing.
- Don't bump `frontend/package.json` — it has tracked an independent `0.1.0`
  since v0.1 and prior releases never touched it.
