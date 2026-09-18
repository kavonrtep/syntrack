import { describe, expect, it } from 'vitest'

import type { Genome } from './api/types'
import { parseCoord, parseRegionInput } from './region_input'

const genome: Genome = {
  id: 'g1',
  label: 'Genome 1',
  total_length: 3000,
  sequences: [
    { name: 'Chr1', length: 1000, offset: 0, color: '#000' },
    { name: 'scaffold:7', length: 2000, offset: 1000, color: '#000' },
  ],
} as unknown as Genome

describe('parseCoord', () => {
  it('parses plain integers and separators', () => {
    expect(parseCoord('1000')).toBe(1000)
    expect(parseCoord('1,000,000')).toBe(1_000_000)
    expect(parseCoord('1_000')).toBe(1000)
  })
  it('parses k / M / G suffixes', () => {
    expect(parseCoord('1.5k')).toBe(1500)
    expect(parseCoord('2M')).toBe(2_000_000)
    expect(parseCoord('0.5g')).toBe(500_000_000)
  })
  it('rejects non-numbers', () => {
    expect(parseCoord('abc')).toBeNull()
    expect(parseCoord('')).toBeNull()
    expect(parseCoord('-5')).toBeNull()
  })
})

describe('parseRegionInput', () => {
  it('accepts seq:from-to and converts 1-based inclusive to 0-based half-open', () => {
    const r = parseRegionInput('Chr1:10-20', genome)
    expect(r).toEqual({ ok: true, region: { seq: 'Chr1', startBp: 9, endBp: 20 } })
  })
  it('accepts seq:from:to', () => {
    const r = parseRegionInput('Chr1:10:20', genome)
    expect(r).toEqual({ ok: true, region: { seq: 'Chr1', startBp: 9, endBp: 20 } })
  })
  it('accepts whitespace-separated form', () => {
    expect(parseRegionInput('Chr1 10 20', genome)).toEqual({
      ok: true,
      region: { seq: 'Chr1', startBp: 9, endBp: 20 },
    })
    expect(parseRegionInput('  Chr1\t10   20 ', genome)).toEqual({
      ok: true,
      region: { seq: 'Chr1', startBp: 9, endBp: 20 },
    })
  })
  it('matches sequence names case-insensitively as a fallback', () => {
    const r = parseRegionInput('chr1:1-5', genome)
    expect(r.ok && r.region.seq).toBe('Chr1')
  })
  it('handles sequence names containing a colon', () => {
    const r = parseRegionInput('scaffold:7:100-200', genome)
    expect(r).toEqual({ ok: true, region: { seq: 'scaffold:7', startBp: 99, endBp: 200 } })
  })
  it('clamps end to the sequence length', () => {
    const r = parseRegionInput('Chr1:900-5000', genome)
    expect(r).toEqual({ ok: true, region: { seq: 'Chr1', startBp: 899, endBp: 1000 } })
  })
  it('rejects unknown sequences', () => {
    const r = parseRegionInput('ChrX:1-5', genome)
    expect(r.ok).toBe(false)
    expect(!r.ok && r.error).toMatch(/Unknown sequence "ChrX"/)
  })
  it('rejects malformed input', () => {
    expect(parseRegionInput('', genome).ok).toBe(false)
    expect(parseRegionInput('Chr1', genome).ok).toBe(false)
    expect(parseRegionInput('Chr1:abc-def', genome).ok).toBe(false)
    expect(parseRegionInput('Chr1:0-10', genome).ok).toBe(false)
    expect(parseRegionInput('Chr1:20-10', genome).ok).toBe(false)
    expect(parseRegionInput('Chr1:2000-3000', genome).ok).toBe(false)
  })
})
