/** Parser for typed region input (``seq:from-to``, ``seq:from:to``,
 *  ``seq from to``) against a genome's sequence list.
 *
 *  Coordinates are 1-based inclusive on input (samtools / IGV convention) and
 *  converted to the app's 0-based half-open ``[startBp, endBp)``. Numbers may
 *  use ``,`` or ``_`` as thousands separators and an optional ``k`` / ``M`` /
 *  ``G`` suffix (``1.2M``). Sequence names are matched exactly against the
 *  genome's ``.fai`` names, then case-insensitively; no naming convention is
 *  assumed. */

import type { Genome, Sequence } from './api/types'

export type ParsedRegion = {
  seq: string
  /** 0-based half-open, clamped to the sequence length. */
  startBp: number
  endBp: number
}

export type RegionParseResult =
  | { ok: true; region: ParsedRegion }
  | { ok: false; error: string }

const SUFFIX: Record<string, number> = { k: 1e3, m: 1e6, g: 1e9 }

/** Parse one coordinate token. Returns null when the token is not a number. */
export function parseCoord(token: string): number | null {
  const t = token.replace(/[,_]/g, '').trim()
  const m = /^(\d+(?:\.\d+)?)([kmg]?)$/i.exec(t)
  if (!m) return null
  const value = Number(m[1]) * (m[2] ? SUFFIX[m[2].toLowerCase()] : 1)
  if (!Number.isFinite(value)) return null
  return Math.round(value)
}

/** Split the raw text into ``[seq, from, to]`` tokens or null. The sequence
 *  name is everything before the last two coordinate tokens, so names that
 *  contain ``:``, ``-`` or spaces still resolve. */
function tokenize(text: string): [string, string, string] | null {
  const s = text.trim()
  if (!s) return null
  // Whitespace form: "seq from to" (seq itself may contain spaces).
  const ws = s.split(/\s+/)
  if (ws.length >= 3) {
    return [ws.slice(0, -2).join(' '), ws[ws.length - 2], ws[ws.length - 1]]
  }
  // Colon form: "seq:from-to" or "seq:from:to". Split on the LAST colon(s).
  const lastColon = s.lastIndexOf(':')
  if (lastColon < 0) return null
  const tail = s.slice(lastColon + 1)
  const head = s.slice(0, lastColon)
  if (/^[^-]+-[^-]+$/.test(tail)) {
    const [from, to] = tail.split('-')
    return [head, from, to]
  }
  // "seq:from:to" → head is "seq:from".
  const prevColon = head.lastIndexOf(':')
  if (prevColon < 0) return null
  return [head.slice(0, prevColon), head.slice(prevColon + 1), tail]
}

export function findSequence(genome: Genome, name: string): Sequence | undefined {
  const exact = genome.sequences.find((s) => s.name === name)
  if (exact) return exact
  const lower = name.toLowerCase()
  return genome.sequences.find((s) => s.name.toLowerCase() === lower)
}

export function parseRegionInput(text: string, genome: Genome): RegionParseResult {
  const tokens = tokenize(text)
  if (!tokens) {
    return { ok: false, error: 'Expected "seq:from-to", "seq:from:to" or "seq from to"' }
  }
  const [seqName, fromTok, toTok] = tokens
  const seq = findSequence(genome, seqName.trim())
  if (!seq) {
    return { ok: false, error: `Unknown sequence "${seqName.trim()}" in ${genome.label}` }
  }
  const from = parseCoord(fromTok)
  const to = parseCoord(toTok)
  if (from === null || to === null) {
    return { ok: false, error: `Coordinates must be numbers (got "${fromTok}", "${toTok}")` }
  }
  if (from < 1) return { ok: false, error: 'Coordinates are 1-based; start must be ≥ 1' }
  if (to < from) return { ok: false, error: `End (${to}) is before start (${from})` }
  if (from > seq.length) {
    return {
      ok: false,
      error: `Start ${from.toLocaleString()} is beyond ${seq.name} length ${seq.length.toLocaleString()}`,
    }
  }
  return {
    ok: true,
    region: { seq: seq.name, startBp: from - 1, endBp: Math.min(to, seq.length) },
  }
}
