#!/usr/bin/env bash
# Create symlinks to source assemblies + SCM BLAST tables, and (re)generate genomes.csv.
# Idempotent: safe to re-run when genomes are added or the assembly list changes.
#
# Usage:  ./link_data.sh
#
# To add a new genome: append its directory name to GENOMES below and re-run.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="/mnt/ceph/454_data/Pisum_pangenome/assemblies"
FAI_REL="pseudomolecules+unanchored.fasta.fai"
BLAST_REL="analysis/painting_probes_CAM/all_oligos/assembly_x_oligos_CAMv2r2.blast_out"

GENOMES=(
  JI1006_2026-01-19
  JI15_2026-01-19
  IPIP201118_2026-01-27
  JI2822_2026-02-02
  IPIP200590_2026-02-04
  JI281_2026-02-05
  IPIP200731_2026-04-14
  IPIP200579_2026-04-14
)

CSV="${SCRIPT_DIR}/genomes.csv"
printf 'genome_id,fai,SCM\n' > "${CSV}"

missing=0
for g in "${GENOMES[@]}"; do
  src_fai="${SOURCE_ROOT}/${g}/${FAI_REL}"
  src_blast="${SOURCE_ROOT}/${g}/${BLAST_REL}"
  dst_fai="${SCRIPT_DIR}/${g}.fai"
  dst_blast="${SCRIPT_DIR}/${g}.blast_out"

  if [[ ! -f "${src_fai}" ]]; then
    echo "MISSING fai: ${src_fai}" >&2
    missing=1
    continue
  fi
  if [[ ! -f "${src_blast}" ]]; then
    echo "MISSING blast: ${src_blast}" >&2
    missing=1
    continue
  fi

  ln -sfn "${src_fai}"   "${dst_fai}"
  ln -sfn "${src_blast}" "${dst_blast}"

  printf '%s,%s,%s\n' "${g}" "${g}.fai" "${g}.blast_out" >> "${CSV}"
  echo "linked ${g}"
done

if [[ "${missing}" -ne 0 ]]; then
  echo "one or more source files were missing; see warnings above" >&2
  exit 1
fi

echo "wrote ${CSV} with ${#GENOMES[@]} genomes"
