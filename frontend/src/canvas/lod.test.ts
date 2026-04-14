import { describe, expect, it } from 'vitest'

import { lodMode } from './lod'

describe('lodMode', () => {
  it('blocks when ppb < 1/threshold', () => {
    expect(lodMode(1 / 100_000, 50_000)).toBe('block') // 1px=100kb > 50kb
  })

  it('scms when ppb > 1/threshold', () => {
    expect(lodMode(1 / 10_000, 50_000)).toBe('scm') // 1px=10kb < 50kb
  })

  it('exact threshold returns block (>= comparison on bp_per_px)', () => {
    expect(lodMode(1 / 50_000, 50_000)).toBe('block')
  })

  it('zero or negative ppb returns block', () => {
    expect(lodMode(0, 50_000)).toBe('block')
    expect(lodMode(-1, 50_000)).toBe('block')
  })
})
