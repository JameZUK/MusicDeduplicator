<script>
  // Every group as a row, for deciding many at once.
  import { store, decide, decisionKind } from '../lib/store.svelte.js';
  import { go } from '../lib/router.svelte.js';
  import { bytes, rel, artistAlbum } from '../lib/format.js';

  let { groups } = $props();

  let identicalOnly = $state(false);
  let lossyOnly = $state(false);
  let selected = $state(new Set());

  const plan = $derived(store.plan);
  const rows = $derived(groups.filter((g) => (!identicalOnly || g.identical) && (!lossyOnly || g.only_lossy_removed)));
  const chosen = $derived(rows.filter((g) => selected.has(g.id)));
  const allOn = $derived(rows.length > 0 && chosen.length === rows.length);
  const chosenBytes = $derived(chosen.reduce((n, g) => n + g.bytes, 0));

  function toggle(id, on) {
    const s = new Set(selected);
    on ? s.add(id) : s.delete(id);
    selected = s;
  }
  const toggleAll = (on) => (selected = on ? new Set(rows.map((g) => g.id)) : new Set());

  function bulk(choice) {
    for (const g of chosen) decide(g.id, choice);
    selected = new Set();
  }

  const label = { undecided: 'to review', accept: 'accepted', skip: 'kept all', changed: 'new keeper' };
</script>

<section class="bulk panel">
  <div class="tools">
    <label class="check"><input type="checkbox" bind:checked={identicalOnly} /> Identical albums only</label>
    <label class="check"><input type="checkbox" bind:checked={lossyOnly} /> Only removes lossy copies</label>
    <span class="count eyebrow">{rows.length} groups</span>
  </div>

  <div class="actions" class:show={chosen.length > 0} aria-live="polite">
    <span><b class="mono">{chosen.length}</b> selected · <span class="mono">{bytes(chosenBytes)}</span></span>
    <button class="btn primary" disabled={!chosen.length} onclick={() => bulk('accept')}>Accept selected</button>
    <button class="btn" disabled={!chosen.length} onclick={() => bulk('skip')}>Keep all copies</button>
    <button class="btn" disabled={!chosen.length} onclick={() => bulk(null)}>Clear decision</button>
  </div>

  <div class="table" role="table" aria-label="Duplicate groups">
    <div class="tr head" role="row">
      <span role="columnheader"><input type="checkbox" checked={allOn} onchange={(e) => toggleAll(e.currentTarget.checked)} aria-label="Select all shown" /></span>
      <span role="columnheader">Album</span>
      <span role="columnheader">Keeps</span>
      <span role="columnheader">Removes</span>
      <span role="columnheader" class="num">Frees</span>
      <span role="columnheader">Status</span>
    </div>
    {#each rows.slice(0, 1000) as g (g.id)}
      {@const aa = artistAlbum(rel(g.keep, plan.roots))}
      {@const kind = decisionKind(g)}
      <div class="tr" role="row" class:on={selected.has(g.id)}>
        <span role="cell"><input type="checkbox" checked={selected.has(g.id)} onchange={(e) => toggle(g.id, e.currentTarget.checked)} aria-label={`Select ${aa.album}`} /></span>
        <span role="cell" class="album">
          <button class="link" onclick={() => go('review', g.id)}>{aa.album}</button>
          <span class="artist">{aa.artist}</span>
        </span>
        <span role="cell" class="mono keep">{g.keep_quality}</span>
        <span role="cell" class="removes">
          {#each g.remove as r}
            <span class="chip mono" class:lossy={r.lossy} title={rel(r.folder, plan.roots)}>{r.quality}{r.kind === 'contained' ? ' ⊂' : ''}</span>
          {/each}
        </span>
        <span role="cell" class="num mono">{bytes(g.bytes)}</span>
        <span role="cell" class={`status ${kind}`}>{label[kind]}</span>
      </div>
    {:else}
      <p class="empty">No groups match.</p>
    {/each}
  </div>
  {#if rows.length > 1000}<p class="empty">Showing 1000 of {rows.length}; filter to narrow.</p>{/if}
  <p class="legend">⊂ = every track is also in the kept folder (an incomplete copy of the same edition).
    Removed copies are never better quality than the one kept.</p>
</section>

<style>
  .bulk { padding: 14px 16px; }
  .tools { display: flex; gap: 18px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; font-size: 13.5px; }
  .check { display: flex; gap: 6px; align-items: center; cursor: pointer; }
  input[type='checkbox'] { accent-color: var(--accent); width: 15px; height: 15px; }
  .count { margin-left: auto; }
  .actions {
    position: sticky; top: 70px; z-index: 2; display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
    padding: 8px 12px; margin-bottom: 8px; border-radius: 10px; background: var(--accent-soft); border: 1px solid var(--accent);
    opacity: .55; transition: opacity .15s;
  }
  .actions.show { opacity: 1; }
  .actions > span:first-child { margin-right: auto; font-size: 13.5px; }
  .tr { display: grid; grid-template-columns: 34px minmax(0, 2.2fr) minmax(0, 1.2fr) minmax(0, 2fr) 90px 100px; gap: 12px; align-items: center;
    padding: 8px 6px; border-bottom: 1px solid var(--line-soft); font-size: 13.5px; }
  .tr.head { font-family: var(--font-mono); font-size: 10.5px; letter-spacing: .12em; text-transform: uppercase; color: var(--ink-3); border-bottom-color: var(--line); }
  .tr.on { background: var(--accent-soft); }
  .album { display: flex; flex-direction: column; min-width: 0; }
  .album .link { all: unset; cursor: pointer; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-decoration: underline; text-decoration-color: var(--line); text-underline-offset: 3px; }
  .album .link:hover { text-decoration-color: var(--accent); }
  .album .link:focus-visible { outline: 2px solid var(--accent); }
  .artist { font-size: 12px; color: var(--ink-3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .keep { color: var(--keep); font-size: 12px; }
  .removes { display: flex; gap: 4px; flex-wrap: wrap; }
  .chip { font-size: 11px; padding: 1px 6px; border-radius: 4px; border: 1px solid var(--remove); color: var(--remove); }
  .chip.lossy { border-style: dashed; }
  .num { text-align: right; }
  .status { font-size: 12px; color: var(--ink-3); }
  .status.accept { color: var(--keep); }
  .status.changed { color: var(--accent); }
  .empty, .legend { color: var(--ink-3); font-size: 12.5px; margin: 10px 4px 0; }
  @media (max-width: 900px) {
    .tr { grid-template-columns: 30px minmax(0, 1fr) 80px; }
    .tr > :nth-child(3), .tr > :nth-child(4), .tr > :nth-child(6) { display: none; }
  }
</style>
