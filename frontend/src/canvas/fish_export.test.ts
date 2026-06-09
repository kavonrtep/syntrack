import { describe, expect, it } from 'vitest'

import type { FishDensityResponse, Genome } from '../api/types'
import { DEFAULT_EXPORT_LAYOUT, exportBins, renderFishDensityImage } from './fish_export'

function genome(id: string): Genome {
  return {
    id,
    label: id,
    total_length: 1000,
    scm_count: 0,
    sequences: [{ name: 'chr1', length: 1000, offset: 0, color: '#888888' }],
  } as unknown as Genome
}

describe('fish_export', () => {
  it('exportBins matches the layout bar width', () => {
    const L = DEFAULT_EXPORT_LAYOUT
    expect(exportBins()).toBe(Math.round(L.width - L.gutter - L.rightPad))
  })

  it('renders a canvas sized to the layout and genome count', () => {
    const density: FishDensityResponse = {
      bins: 2,
      sets: [{ label: 'red', color: '#ff0000', scm_count: 1, max_count: 1, genomes: { A: [1, 0] } }],
    }
    const genomes = [genome('A'), genome('B')]
    const canvas = renderFishDensityImage(density, genomes, new Set(['red']))
    const L = DEFAULT_EXPORT_LAYOUT
    expect(canvas.width).toBe(L.width)
    expect(canvas.height).toBe(L.topPad + genomes.length * (L.barHeight + L.gap) + L.bottomPad)
  })
})
