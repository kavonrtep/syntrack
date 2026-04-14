<script lang="ts">
  import { onMount } from 'svelte'

  import { api } from './api/client'
  import type { Genome } from './api/types'

  let genomes = $state<Genome[] | null>(null)
  let universeSize = $state(0)
  let error = $state<string | null>(null)

  onMount(async () => {
    try {
      const r = await api.genomes()
      genomes = r.genomes
      universeSize = r.scm_universe_size
    } catch (err) {
      error = err instanceof Error ? err.message : String(err)
    }
  })

  function fmtBp(n: number): string {
    if (n >= 1e9) return `${(n / 1e9).toFixed(2)} Gb`
    if (n >= 1e6) return `${(n / 1e6).toFixed(0)} Mb`
    if (n >= 1e3) return `${(n / 1e3).toFixed(0)} kb`
    return `${n} bp`
  }
</script>

<header>
  <h1>SynTrack</h1>
</header>

<main>
  {#if error}
    <div class="error">{error}</div>
  {:else if genomes === null}
    <p>Loading genomes…</p>
  {:else}
    <p class="summary">
      {genomes.length} genome{genomes.length === 1 ? '' : 's'} loaded —
      {universeSize.toLocaleString()} unique SCMs
    </p>
    <ul class="genome-list">
      {#each genomes as g (g.id)}
        <li>
          <strong>{g.label}</strong>
          <span class="meta">
            {g.scm_count.toLocaleString()} SCMs ·
            {g.sequences.length} sequence{g.sequences.length === 1 ? '' : 's'} ·
            {fmtBp(g.total_length)}
          </span>
        </li>
      {/each}
    </ul>
  {/if}
</main>

<style>
  header {
    padding: 0.6em 1em;
    border-bottom: 1px solid #333;
    background: #232323;
  }

  h1 {
    margin: 0;
    font-size: 1.2em;
    font-weight: 500;
  }

  main {
    flex: 1;
    overflow: auto;
    padding: 1em;
  }

  .summary {
    color: #aaa;
    margin: 0 0 1em 0;
  }

  .genome-list {
    list-style: none;
    padding: 0;
    margin: 0;
  }

  .genome-list li {
    padding: 0.5em 0.8em;
    border-bottom: 1px solid #2a2a2a;
    display: flex;
    justify-content: space-between;
    gap: 1em;
  }

  .meta {
    color: #888;
    font-variant-numeric: tabular-nums;
  }
</style>
