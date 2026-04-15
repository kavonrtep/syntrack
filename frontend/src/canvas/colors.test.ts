import { describe, expect, it } from 'vitest'

import type { Genome } from '../api/types'
import { UNKNOWN_COLOR, colorFor, referenceColorMap } from './colors'

function mkGenome(id: string, seqs: [string, string][]): Genome {
  return {
    id,
    label: id,
    total_length: 100 * seqs.length,
    scm_count: 0,
    sequences: seqs.map(([name, color], i) => ({
      name,
      length: 100,
      offset: i * 100,
      color,
    })),
    filtering: {
      raw_hits: 0,
      after_quality: 0,
      after_uniqueness: 0,
      after_validation: 0,
      discarded_quality_rows: 0,
      discarded_multicopy_scms: 0,
      discarded_validation_scms: 0,
    },
  }
}

describe('referenceColorMap', () => {
  it('returns seq name → palette color', () => {
    const ref = mkGenome('A', [
      ['chr1', '#ff0000'],
      ['chr2', '#00ff00'],
    ])
    const map = referenceColorMap(ref)
    expect(map.get('chr1')).toBe('#ff0000')
    expect(map.get('chr2')).toBe('#00ff00')
    expect(map.size).toBe(2)
  })
})

describe('colorFor', () => {
  const map = new Map([['chr1', '#ff0000']])

  it('returns palette color for known reference seq', () => {
    expect(colorFor('chr1', map)).toBe('#ff0000')
  })

  it('returns UNKNOWN_COLOR for null', () => {
    expect(colorFor(null, map)).toBe(UNKNOWN_COLOR)
  })

  it('returns UNKNOWN_COLOR for undefined', () => {
    expect(colorFor(undefined, map)).toBe(UNKNOWN_COLOR)
  })

  it('returns UNKNOWN_COLOR for unknown seq name', () => {
    expect(colorFor('never_seen', map)).toBe(UNKNOWN_COLOR)
  })
})
