import { describe, expect, it } from 'vitest'

import type { HighlightResponse } from './api/types'
import {
  buildPresenceTsv,
  presenceFromBitstrings,
  presenceFromHighlight,
  safeFilenamePart,
} from './scm_export'

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

describe('safeFilenamePart', () => {
  it('collapses runs of unsafe characters into one underscore', () => {
    expect(safeFilenamePart('chr6:0-60550389 JI2202')).toBe('chr6_0-60550389_JI2202')
    expect(safeFilenamePart('chr6:0-60550389 JI2202 (2)')).toBe('chr6_0-60550389_JI2202_2')
  })
  it('keeps safe characters and trims edge underscores', () => {
    expect(safeFilenamePart('JI1006_2026-01-19.set')).toBe('JI1006_2026-01-19.set')
    expect(safeFilenamePart(' chr1 ')).toBe('chr1')
  })
})

describe('presenceFromHighlight', () => {
  const resp = (): HighlightResponse => ({
    source: {
      genome_id: 'A',
      seq: 'chr1',
      start: 0,
      end: 1000,
      scm_count: 3,
      scm_ids: ['OG01', 'OG02', 'OG03'],
      truncated: false,
    },
    targets: [
      {
        genome_id: 'B',
        scm_count: 2,
        truncated: false,
        positions: [
          { scm_id: 'OG01', seq: 'chr1', start: 10, end: 20, strand: '+' },
          { scm_id: 'OG03', seq: 'chr1', start: 30, end: 40, strand: '+' },
        ],
      },
      {
        genome_id: 'C',
        scm_count: 1,
        truncated: false,
        positions: [{ scm_id: 'OG02', seq: 'chr2', start: 50, end: 60, strand: '-' }],
      },
    ],
  })

  it('marks the source genome present for every SCM', () => {
    const presence = presenceFromHighlight(resp())
    expect([...presence.keys()]).toEqual(['OG01', 'OG02', 'OG03'])
    for (const genomes of presence.values()) expect(genomes.has('A')).toBe(true)
  })

  it('marks a target present only where that SCM occurs', () => {
    const presence = presenceFromHighlight(resp())
    expect([...presence.get('OG01')!].sort()).toEqual(['A', 'B'])
    expect([...presence.get('OG02')!].sort()).toEqual(['A', 'C'])
    expect([...presence.get('OG03')!].sort()).toEqual(['A', 'B'])
  })

  it('produces the TSV the download writes', () => {
    const presence = presenceFromHighlight(resp())
    const lines = buildPresenceTsv(resp().source.scm_ids, presence, ['A', 'B', 'C'])
      .trimEnd()
      .split('\n')
    expect(lines[0]).toBe('scm_id\tpresent_in\tA\tB\tC')
    expect(lines[1]).toBe('OG01\t2\t1\t1\t0')
    expect(lines[2]).toBe('OG02\t2\t1\t0\t1')
    expect(lines[3]).toBe('OG03\t2\t1\t1\t0')
  })

  it('ignores a target position outside the source set rather than inventing a row', () => {
    const r = resp()
    r.targets[0].positions.push({
      scm_id: 'OG99',
      seq: 'chr1',
      start: 0,
      end: 1,
      strand: '+',
    })
    const presence = presenceFromHighlight(r)
    expect(presence.has('OG99')).toBe(false)
    expect(presence.size).toBe(3)
  })

  it('handles an empty highlight', () => {
    const r = resp()
    r.source.scm_ids = []
    r.targets = []
    expect(presenceFromHighlight(r).size).toBe(0)
  })
})
