// Reference-propagated color resolution (design §5.7, v0.1.1).
//
// Colors come from the *reference* genome — the top genome in the current
// order. Each SCM carries its reference_seq (from the backend); the renderer
// looks up that sequence name in the reference genome's palette. SCMs absent
// from the reference fall back to UNKNOWN_COLOR.

import type { Genome } from '../api/types'

export const UNKNOWN_COLOR = '#3a3a3a'
// Fallback for SCMs that have no hit in the reference genome.
// Chosen to be darker than the default palette's "minor" color (#888),
// so "absent from reference" is visually distinct from "on a short scaffold".

/** Build a ``{ seqName → hex }`` lookup table from a reference genome's sequences. */
export function referenceColorMap(reference: Genome): Map<string, string> {
  return new Map(reference.sequences.map((s) => [s.name, s.color]))
}

/** Resolve color from a reference-seq name. ``null`` / unknown → :data:`UNKNOWN_COLOR`. */
export function colorFor(referenceSeq: string | null | undefined, refMap: Map<string, string>): string {
  if (!referenceSeq) return UNKNOWN_COLOR
  return refMap.get(referenceSeq) ?? UNKNOWN_COLOR
}
