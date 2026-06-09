import { describe, expect, it } from 'vitest'

import type { FishDensitySet, Genome } from '../api/types'
import { drawFishDensity } from './draw_fish_density'

function genome(id: string): Genome {
  return {
    id,
    label: id,
    total_length: 1000,
    scm_count: 0,
    sequences: [{ name: 'chr1', length: 1000, offset: 0, color: '#888888' }],
  } as unknown as Genome
}

type Fill = { style: string; x: number; w: number }

function recordingCtx(): { ctx: unknown; fills: Fill[] } {
  const fills: Fill[] = []
  const ctx = {
    fillStyle: '',
    clearRect: () => {},
    fillRect(x: number, _y: number, w: number) {
      fills.push({ style: (ctx as { fillStyle: string }).fillStyle, x, w })
    },
  }
  return { ctx, fills }
}

describe('drawFishDensity', () => {
  it('composites a single set as colour × intensity on its bins', () => {
    const { ctx, fills } = recordingCtx()
    const sets: FishDensitySet[] = [
      { label: 'red', color: '#ff0000', scm_count: 4, max_count: 4, genomes: { A: [4, 0] } },
    ]
    drawFishDensity(ctx as never, sets, new Set(['red']), [genome('A')], 2, 100, 50)

    // Full-intensity red signal in bin 0 (sqrt(4/4) = 1 -> 255).
    const signal = fills.filter((f) => f.style === 'rgb(255, 0, 0)')
    expect(signal.length).toBe(1)
    expect(signal[0].x).toBe(0) // bin 0 at x=0
    // A dark background bar is painted across the full width first.
    expect(fills.some((f) => f.w >= 100)).toBe(true)
  })

  it('blends overlapping sets additively (red + green -> yellow)', () => {
    const { ctx, fills } = recordingCtx()
    const sets: FishDensitySet[] = [
      { label: 'red', color: '#ff0000', scm_count: 1, max_count: 1, genomes: { A: [1] } },
      { label: 'green', color: '#00ff00', scm_count: 1, max_count: 1, genomes: { A: [1] } },
    ]
    drawFishDensity(ctx as never, sets, new Set(['red', 'green']), [genome('A')], 1, 100, 50)
    expect(fills.some((f) => f.style === 'rgb(255, 255, 0)')).toBe(true)
  })

  it('honours visibility — a hidden set contributes nothing', () => {
    const { ctx, fills } = recordingCtx()
    const sets: FishDensitySet[] = [
      { label: 'red', color: '#ff0000', scm_count: 1, max_count: 1, genomes: { A: [1] } },
    ]
    drawFishDensity(ctx as never, sets, new Set(), [genome('A')], 1, 100, 50)
    expect(fills.some((f) => f.style.startsWith('rgb(255'))).toBe(false)
  })
})
