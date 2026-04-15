import { describe, expect, it } from 'vitest'

import { DEFAULT_LAYOUT, trackY } from './draw_tracks'
import { genomeIndexAt } from './hit_test'

const L = DEFAULT_LAYOUT

describe('genomeIndexAt', () => {
  it('returns null before any track', () => {
    expect(genomeIndexAt(0, 3)).toBe(null)
  })

  it('returns 0 at top of first track', () => {
    expect(genomeIndexAt(trackY(0, L), 3)).toBe(0)
  })

  it('returns 0 anywhere inside first track', () => {
    expect(genomeIndexAt(trackY(0, L) + L.trackHeight / 2, 3)).toBe(0)
  })

  it('returns null in the gap between tracks', () => {
    // gap starts at trackY(0) + trackHeight
    const gapY = trackY(0, L) + L.trackHeight + L.trackGap / 2
    expect(genomeIndexAt(gapY, 3)).toBe(null)
  })

  it('returns 1 inside second track', () => {
    expect(genomeIndexAt(trackY(1, L) + 5, 3)).toBe(1)
  })

  it('returns null past the last track', () => {
    const beyond = trackY(2, L) + L.trackHeight + 50
    expect(genomeIndexAt(beyond, 3)).toBe(null)
  })

  it('returns null when trackCount is 0', () => {
    expect(genomeIndexAt(100, 0)).toBe(null)
  })

  it('half-open on bottom edge (y == top + height exits the track)', () => {
    expect(genomeIndexAt(trackY(0, L) + L.trackHeight, 3)).toBe(null)
  })
})
