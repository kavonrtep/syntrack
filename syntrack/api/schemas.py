"""Pydantic schemas for the public API. Internal dataclasses live in syntrack.model."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------ /api/genomes ------------------------------


class SequenceSchema(_Schema):
    name: str
    length: int
    offset: int
    color: str


class FilteringStatsSchema(_Schema):
    raw_hits: int
    after_quality: int
    after_uniqueness: int
    after_validation: int
    discarded_quality_rows: int
    discarded_multicopy_scms: int
    discarded_validation_scms: int


class GenomeSchema(_Schema):
    id: str
    label: str
    total_length: int
    scm_count: int
    sequences: list[SequenceSchema]
    filtering: FilteringStatsSchema


class GenomesResponse(_Schema):
    genomes: list[GenomeSchema]
    scm_universe_size: int


# ------------------------------ /api/pairs --------------------------------


class PairSummary(_Schema):
    genome1_id: str
    genome2_id: str
    shared_scm_count: int
    derived: bool
    block_count: int | None = None
    cached_on_disk: bool = False  # always false in v0.1 (in-memory only)


class PairsResponse(_Schema):
    pairs: list[PairSummary]


# ------------------------------ /api/synteny/blocks ----------------------


class SyntenyBlockSchema(_Schema):
    block_id: int
    g1_seq: str
    g1_start: int
    g1_end: int
    g2_seq: str
    g2_start: int
    g2_end: int
    strand: str = Field(pattern=r"^[+-]$")
    scm_count: int
    reference_seq: str | None = None
    """Dominant sequence name in the reference genome among this block's SCMs.
    ``null`` if no ``reference`` query param was given, or no SCM in this block
    is present in the reference genome."""


class BlocksResponse(_Schema):
    pair: tuple[str, str]
    shared_scm_count: int
    block_count: int
    blocks: list[SyntenyBlockSchema]


# ------------------------------ /api/synteny/scms ------------------------


class PairwiseSCMSchema(_Schema):
    scm_id: str
    g1_seq: str
    g1_start: int
    g1_end: int
    g2_seq: str
    g2_start: int
    g2_end: int
    strand: str = Field(pattern=r"^[+-]$")
    reference_seq: str | None = None
    """Sequence in the reference genome that contains this SCM, or ``null`` if the
    SCM is absent from the reference / no ``reference`` query param was given."""


class SCMsResponse(_Schema):
    pair: tuple[str, str]
    scms: list[PairwiseSCMSchema]
    total_in_region: int
    returned: int
    downsampled: bool


# ------------------------------ /api/scm/{id} -----------------------------


class SCMPositionSchema(_Schema):
    genome_id: str
    seq: str
    start: int
    end: int
    strand: str = Field(pattern=r"^[+-]$")


class SCMResponse(_Schema):
    scm_id: str
    present_in: int
    positions: list[SCMPositionSchema]


# ------------------------------ /api/highlight ----------------------------


class HighlightSourceSchema(_Schema):
    genome_id: str
    seq: str
    start: int
    end: int
    scm_count: int


class HighlightPositionSchema(_Schema):
    scm_id: str
    seq: str
    start: int
    end: int
    strand: str = Field(pattern=r"^[+-]$")


class HighlightTargetSchema(_Schema):
    genome_id: str
    scm_count: int
    positions: list[HighlightPositionSchema]


class HighlightResponse(_Schema):
    source: HighlightSourceSchema
    targets: list[HighlightTargetSchema]


# ------------------------------ /api/align --------------------------------


class AlignmentSourceSchema(_Schema):
    genome_id: str
    seq: str
    pos: int


class AlignmentMappingSchema(_Schema):
    genome_id: str
    seq: str | None
    """Target sequence name, or ``null`` if no blocks map ``seq`` to this genome."""
    pos: int | None
    confidence: float
    """1.0 when the clicked bp falls inside a block; decays with distance otherwise."""


class AlignmentResponse(_Schema):
    source: AlignmentSourceSchema
    mappings: list[AlignmentMappingSchema]


# ------------------------------ /api/paint --------------------------------


class PaintRegionSchema(_Schema):
    """One contiguous run of SCMs on ``(genome_id, seq)`` that share the same
    reference_seq (or all lack one)."""

    seq: str
    start: int
    end: int
    reference_seq: str | None
    scm_count: int


class PaintResponse(_Schema):
    genome_id: str
    reference: str
    regions: list[PaintRegionSchema]


# ------------------------------ /api/config -------------------------------


class BlockDetectionSchema(_Schema):
    max_gap: int = Field(ge=1)
    min_block_size: int = Field(ge=1)


class BlastFilteringSchema(_Schema):
    min_pident: float
    min_length: int
    max_evalue: float
    uniqueness_ratio: float


class RenderingDefaultsSchema(_Schema):
    block_threshold_bp_per_px: int
    max_visible_scms: int
    connection_opacity: float
    highlight_opacity: float
    dimmed_opacity: float


class ConfigResponse(_Schema):
    block_detection: BlockDetectionSchema
    blast_filtering: BlastFilteringSchema
    rendering_defaults: RenderingDefaultsSchema


class ConfigUpdate(_Schema):
    """Currently only block_detection is mutable at runtime (design §3.3)."""

    block_detection: BlockDetectionSchema
