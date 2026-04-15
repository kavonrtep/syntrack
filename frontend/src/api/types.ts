// Mirrors syntrack/api/schemas.py.
// Keep field names in sync — the backend rejects unknown fields strictly.

export type Sequence = {
  name: string
  length: number
  offset: number
  color: string
}

export type FilteringStats = {
  raw_hits: number
  after_quality: number
  after_uniqueness: number
  after_validation: number
  discarded_quality_rows: number
  discarded_multicopy_scms: number
  discarded_validation_scms: number
}

export type Genome = {
  id: string
  label: string
  total_length: number
  scm_count: number
  sequences: Sequence[]
  filtering: FilteringStats
}

export type GenomesResponse = {
  genomes: Genome[]
  scm_universe_size: number
}

export type PairSummary = {
  genome1_id: string
  genome2_id: string
  shared_scm_count: number
  derived: boolean
  block_count: number | null
  cached_on_disk: boolean
}

export type PairsResponse = { pairs: PairSummary[] }

export type Strand = '+' | '-'

export type SyntenyBlock = {
  block_id: number
  g1_seq: string
  g1_start: number
  g1_end: number
  g2_seq: string
  g2_start: number
  g2_end: number
  strand: Strand
  scm_count: number
  reference_seq: string | null
}

export type BlocksResponse = {
  pair: [string, string]
  shared_scm_count: number
  block_count: number
  blocks: SyntenyBlock[]
}

export type PairwiseSCM = {
  scm_id: string
  g1_seq: string
  g1_start: number
  g1_end: number
  g2_seq: string
  g2_start: number
  g2_end: number
  strand: Strand
  reference_seq: string | null
}

export type SCMsResponse = {
  pair: [string, string]
  scms: PairwiseSCM[]
  total_in_region: number
  returned: number
  downsampled: boolean
}

export type SCMPosition = {
  genome_id: string
  seq: string
  start: number
  end: number
  strand: Strand
}

export type SCMResponse = {
  scm_id: string
  present_in: number
  positions: SCMPosition[]
}

export type PaintRegion = {
  seq: string
  start: number
  end: number
  reference_seq: string | null
  scm_count: number
}

export type PaintResponse = {
  genome_id: string
  reference: string
  regions: PaintRegion[]
}

export type AlignmentMapping = {
  genome_id: string
  seq: string | null
  pos: number | null
  confidence: number
}

export type AlignmentResponse = {
  source: { genome_id: string; seq: string; pos: number }
  mappings: AlignmentMapping[]
}

export type HighlightPosition = {
  scm_id: string
  seq: string
  start: number
  end: number
  strand: Strand
}

export type HighlightTarget = {
  genome_id: string
  scm_count: number
  positions: HighlightPosition[]
}

export type HighlightResponse = {
  source: {
    genome_id: string
    seq: string
    start: number
    end: number
    scm_count: number
  }
  targets: HighlightTarget[]
}

export type BlockDetection = { max_gap: number; min_block_size: number }
export type BlastFiltering = {
  min_pident: number
  min_length: number
  max_evalue: number
  uniqueness_ratio: number
}
export type RenderingDefaults = {
  block_threshold_bp_per_px: number
  max_visible_scms: number
  connection_opacity: number
  highlight_opacity: number
  dimmed_opacity: number
}

export type ConfigResponse = {
  block_detection: BlockDetection
  blast_filtering: BlastFiltering
  rendering_defaults: RenderingDefaults
}
