// Tiny formatting helpers for genomic units.

export function fmtBp(n: number): string {
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)} Gb`
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)} Mb`
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)} kb`
  return `${Math.round(n)} bp`
}

export function fmtBpExact(n: number): string {
  return Math.round(n).toLocaleString() + ' bp'
}
