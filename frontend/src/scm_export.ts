// Shared SCM-ID export helpers, used by both the highlight download and the
// per-marker-set "save to file" action so they produce an identical, reloadable
// TSV: scm_id, present_in (genome count), then one 0/1 column per loaded genome.

/** Build the SCM presence-matrix TSV. `presence` maps each scm_id to the set of
 *  genome ids it occurs in; `genomeIds` fixes the column order. */
export function buildPresenceTsv(
  scmIds: string[],
  presence: Map<string, Set<string>>,
  genomeIds: string[],
): string {
  const header = ['scm_id', 'present_in', ...genomeIds].join('\t')
  const lines = [header]
  for (const scmId of scmIds) {
    const set = presence.get(scmId) ?? new Set<string>()
    lines.push(
      [scmId, String(set.size), ...genomeIds.map((g) => (set.has(g) ? '1' : '0'))].join('\t'),
    )
  }
  return lines.join('\n') + '\n'
}

/** Build a presence map from the backend's per-genome '0'/'1' bitstrings
 *  (aligned to `scmIds`). */
export function presenceFromBitstrings(
  scmIds: string[],
  bitstrings: Record<string, string>,
): Map<string, Set<string>> {
  const genomeIds = Object.keys(bitstrings)
  const presence = new Map<string, Set<string>>()
  for (let i = 0; i < scmIds.length; i++) {
    const s = new Set<string>()
    for (const g of genomeIds) {
      if (bitstrings[g]?.[i] === '1') s.add(g)
    }
    presence.set(scmIds[i], s)
  }
  return presence
}

export function downloadTextFile(
  text: string,
  filename: string,
  mime = 'text/tab-separated-values;charset=utf-8',
): void {
  const blob = new Blob([text], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

/** Sanitize a label for use in a filename. */
export function safeFilenamePart(s: string): string {
  return s.replace(/[^A-Za-z0-9._-]/g, '_')
}
