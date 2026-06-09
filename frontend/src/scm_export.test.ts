import { describe, expect, it } from 'vitest'

import { buildPresenceTsv, presenceFromBitstrings } from './scm_export'

describe('scm_export', () => {
  it('builds a presence-matrix TSV with stable genome column order', () => {
    const presence = new Map([
      ['OG01', new Set(['A', 'B'])],
      ['OG05', new Set(['A', 'B', 'C'])],
    ])
    const tsv = buildPresenceTsv(['OG01', 'OG05'], presence, ['A', 'B', 'C'])
    const lines = tsv.trimEnd().split('\n')
    expect(lines[0]).toBe('scm_id\tpresent_in\tA\tB\tC')
    expect(lines[1]).toBe('OG01\t2\t1\t1\t0')
    expect(lines[2]).toBe('OG05\t3\t1\t1\t1')
  })

  it('reconstructs presence from per-genome bitstrings aligned to scm_ids', () => {
    const presence = presenceFromBitstrings(['OG01', 'OG05'], { A: '11', B: '11', C: '01' })
    expect(presence.get('OG01')).toEqual(new Set(['A', 'B']))
    expect(presence.get('OG05')).toEqual(new Set(['A', 'B', 'C']))
  })

  it('round-trips backend bitstrings into the same TSV', () => {
    const ids = ['OG01', 'OG05']
    const presence = presenceFromBitstrings(ids, { A: '11', B: '11', C: '01' })
    const tsv = buildPresenceTsv(ids, presence, ['A', 'B', 'C'])
    expect(tsv).toContain('OG01\t2\t1\t1\t0')
    expect(tsv).toContain('OG05\t3\t1\t1\t1')
  })
})
