<script>
  import { store, decide, decisionKind } from '../lib/store.svelte.js';
  import { go, route, setQuery } from '../lib/router.svelte.js';
  import { bytes, rel, artistAlbum } from '../lib/format.js';
  import GroupDetail from './GroupDetail.svelte';
  import BulkList from './BulkList.svelte';

  let { id = null } = $props();

  const filters = [
    ['undecided', 'To review'],
    ['accept', 'Accepted'],
    ['changed', 'New keeper'],
    ['skip', 'Skipped'],
    ['all', 'All'],
  ];
  let filter = $state('undecided');
  const listMode = $derived(route.query.mode === 'list');
  let query = $state('');

  const plan = $derived(store.plan);
  const groups = $derived(
    plan.groups.filter((g) => {
      if (filter !== 'all' && decisionKind(g) !== filter) return false;
      if (!query) return true;
      const q = query.toLowerCase();
      return [g.keep, ...g.remove.map((r) => r.folder)].some((p) => p.toLowerCase().includes(q));
    }),
  );
  const counts = $derived(Object.fromEntries(filters.map(([k]) => [k,
    k === 'all' ? plan.groups.length : plan.groups.filter((g) => decisionKind(g) === k).length])));

  const current = $derived(
    (id !== null && plan.groups.find((g) => String(g.id) === String(id))) || groups[0] || null,
  );

  function step(delta) {
    const list = groups.length ? groups : plan.groups;
    const i = list.findIndex((g) => g.id === current?.id);
    const next = list[Math.min(list.length - 1, Math.max(0, i + delta))];
    if (next) go('review', next.id);
  }

  function choose(choice) {
    if (!current) return;
    const before = current.id;
    decide(before, choice);
    // In the "to review" list the decided group drops out; move to what's next.
    if (filter === 'undecided') {
      const rest = groups.filter((g) => g.id !== before);
      if (rest.length) go('review', rest[0].id);
    } else {
      step(1);
    }
  }

  function onkey(e) {
    // Not while the comparison panel or a dialog is open: their keys mean other things.
    if (route.query.a || listMode || document.querySelector('dialog[open]')) return;
    if ((e.target instanceof Element && e.target.closest('input, textarea, select')) || e.metaKey || e.ctrlKey || e.altKey) return;
    const k = e.key.toLowerCase();
    if (k === 'j' || e.key === 'ArrowDown') { step(1); e.preventDefault(); }
    else if (k === 'k' || e.key === 'ArrowUp') { step(-1); e.preventDefault(); }
    else if (k === 'a') choose('accept');
    else if (k === 's') choose('skip');
    else if (k === 'u' && current) decide(current.id, null);
  }

  const badge = { undecided: '', accept: '✓', skip: '–', changed: '⇄' };
</script>

<svelte:window onkeydown={onkey} />

<div class="modebar">
  <div class="modes" role="radiogroup" aria-label="Review mode">
    <button role="radio" aria-checked={!listMode} class:on={!listMode} onclick={() => setQuery({ mode: null })}>One by one</button>
    <button role="radio" aria-checked={listMode} class:on={listMode} onclick={() => setQuery({ mode: 'list', copy: null })}>List · bulk</button>
  </div>
</div>

{#if listMode}
  <div class="listfilters" role="tablist">
    {#each filters as [key, label]}
      <button role="tab" aria-selected={filter === key} class:on={filter === key} onclick={() => (filter = key)}>
        {label} <span class="mono">{counts[key]}</span>
      </button>
    {/each}
    <input class="search" type="search" placeholder="Filter by artist or album" bind:value={query} />
  </div>
  <BulkList {groups} />
{:else}
<div class="review">
  <aside class="queue panel" aria-label="Duplicate groups">
    <div class="filters" role="tablist">
      {#each filters as [key, label]}
        <button role="tab" aria-selected={filter === key} class:on={filter === key} onclick={() => (filter = key)}>
          {label} <span class="mono">{counts[key]}</span>
        </button>
      {/each}
    </div>
    <input class="search" type="search" placeholder="Filter by artist or album" bind:value={query} />
    <ol>
      {#each groups.slice(0, 400) as g (g.id)}
        {@const kind = decisionKind(g)}
        {@const aa = artistAlbum(rel(g.keep, plan.roots))}
        <li>
          <a href={`#/review/${g.id}`} class:active={current?.id === g.id} class={kind}>
            <span class="state" aria-label={kind}>{badge[kind]}</span>
            <span class="names">
              <span class="album">{aa.album}</span>
              <span class="artist">{aa.artist}</span>
            </span>
            <span class="meta mono">{g.remove.length + 1}× · {bytes(g.bytes)}</span>
          </a>
        </li>
      {:else}
        <li class="empty">{filter === 'undecided' ? 'Everything is decided. Apply when ready.' : 'Nothing here.'}</li>
      {/each}
      {#if groups.length > 400}<li class="empty">Showing 400 of {groups.length}; filter to narrow.</li>{/if}
    </ol>
    <p class="keys"><kbd>J</kbd><kbd>K</kbd> move <kbd>A</kbd> accept <kbd>S</kbd> skip <kbd>U</kbd> undo</p>
  </aside>

  <section class="detail">
    {#if current}
      {#key current.id}
        <GroupDetail group={current} onchoose={choose} onstep={step} />
      {/key}
    {:else}
      <div class="panel nothing">
        <h2>No duplicate groups</h2>
        <p>The scan found no folders that copy another. Nothing to review.</p>
      </div>
    {/if}
  </section>
</div>
{/if}

<style>
  .modebar { display: flex; justify-content: flex-end; margin: -8px 0 14px; }
  .modes { display: flex; border: 1px solid var(--line); border-radius: 999px; overflow: hidden; }
  .modes button { border: 0; background: none; padding: 5px 14px; font-size: 13px; color: var(--ink-2); }
  .modes button.on { background: var(--panel-2); color: var(--ink); box-shadow: inset 0 0 0 1px var(--accent); border-radius: 999px; }
  .listfilters { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin-bottom: 12px; }
  .listfilters button { border: 1px solid var(--line-soft); background: none; border-radius: 999px; padding: 3px 10px; font-size: 12.5px; color: var(--ink-2); }
  .listfilters button.on { border-color: var(--accent); color: var(--ink); background: var(--accent-soft); }
  .listfilters .mono { font-size: 11px; color: var(--ink-3); }
  .listfilters .search { margin: 0 0 0 auto; min-width: 240px; }
  .review { display: grid; grid-template-columns: 330px minmax(0, 1fr); gap: 22px; align-items: start; }

  .queue { position: sticky; top: 76px; max-height: calc(100vh - 100px); display: flex; flex-direction: column; overflow: hidden; }
  .filters { display: flex; flex-wrap: wrap; gap: 4px; padding: 12px 12px 8px; }
  .filters button {
    border: 1px solid var(--line-soft); background: none; border-radius: 999px; padding: 3px 9px;
    font-size: 12.5px; color: var(--ink-2);
  }
  .filters button.on { border-color: var(--accent); color: var(--ink); background: var(--accent-soft); }
  .filters .mono { font-size: 11px; color: var(--ink-3); margin-left: 2px; }
  .search {
    margin: 0 12px 8px; padding: 7px 11px; border-radius: var(--radius-sm); border: 1px solid var(--line);
    background: var(--panel-2); color: var(--ink); font: inherit; font-size: 13.5px;
  }
  ol { list-style: none; margin: 0; padding: 0 6px 6px; overflow-y: auto; flex: 1; }
  li a {
    display: grid; grid-template-columns: 18px minmax(0, 1fr) auto; gap: 10px; align-items: center;
    padding: 8px 8px; border-radius: var(--radius-sm); text-decoration: none; border-left: 2px solid transparent;
  }
  li a:hover { background: var(--panel-2); }
  li a.active { background: var(--panel-2); border-left-color: var(--accent); }
  .state { font-family: var(--font-mono); font-size: 13px; text-align: center; color: var(--ink-3); }
  a.accept .state { color: var(--keep); }
  a.changed .state { color: var(--accent); }
  a.skip { opacity: .6; }
  .names { min-width: 0; display: flex; flex-direction: column; }
  .album, .artist { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .album { font-size: 14px; }
  .artist { font-size: 12px; color: var(--ink-3); }
  .meta { font-size: 11px; color: var(--ink-3); }
  .empty { padding: 18px 12px; color: var(--ink-3); font-size: 13.5px; }
  @media (hover: none) and (pointer: coarse) { .keys { display: none !important; } }
  .keys { margin: 0; padding: 10px 14px; border-top: 1px solid var(--line-soft); font-size: 11.5px; color: var(--ink-3); display: flex; gap: 4px; align-items: center; flex-wrap: wrap; }

  .nothing { padding: 40px; text-align: center; }
  .nothing p { color: var(--ink-3); }

  @media (max-width: 900px) {
    .review { grid-template-columns: 1fr; }
    .queue { position: static; max-height: 230px; }
  }
</style>
