<script>
  // Two track lists with "patch cables" joining each track to its same-audio copy.
  // Reordered tracks visibly cross; unmatched tracks have no cable.
  import { openCompare } from '../lib/router.svelte.js';
  import { player, load, play, pause, setOffset } from '../lib/player.svelte.js';
  import { api } from '../lib/api.js';
  import { rel, base, time } from '../lib/format.js';
  import Quality from './Quality.svelte';

  let { detail, keep, other, roots } = $props();

  const ROW = 38;
  let hover = $state(null);

  const left = $derived(detail.folders[keep]?.tracks ?? []);
  const right = $derived(detail.folders[other]?.tracks ?? []);
  const leftIndex = $derived(new Map(left.map((t, i) => [t.path, i])));
  const cables = $derived(
    right.flatMap((t, j) => {
      const pair = detail.pairs.find((p) => p.remove === t.path);
      const i = pair ? leftIndex.get(pair.keep) : undefined;
      return i === undefined ? [] : [{ i, j, a: pair.keep, b: t.path }];
    }),
  );
  const matchedLeft = $derived(new Set(cables.map((c) => c.i)));
  const matchedRight = $derived(new Set(cables.map((c) => c.j)));
  const height = $derived(Math.max(left.length, right.length) * ROW);

  const title = (t) => t.title || base(t.path).replace(/\.[^.]+$/, '');
  const y = (n) => n * ROW + ROW / 2;
  const path = (c) => `M0 ${y(c.i)} C 60 ${y(c.i)}, 60 ${y(c.j)}, 120 ${y(c.j)}`;
  const open = (c) => openCompare(c.a, c.b);

  /** Plays the pair in the player bar: kept copy as A, this copy as B. */
  async function listen(c) {
    if (player.a === c.a && player.b === c.b && player.playing) return pause();
    load(c.a, c.b, { labelA: 'Kept', labelB: 'This copy' });
    await play();
    api.compare(c.a, c.b).then((p) => setOffset(p.offset_seconds || 0)).catch(() => {});
  }
  const isPlaying = (c) => player.playing && player.a === c.a && player.b === c.b;
</script>

<section class="bay panel">
  <header>
    <div class="col-head keep"><span class="eyebrow">kept</span><span class="name" title={keep}>{rel(keep, roots)}</span></div>
    <div class="gutter-head eyebrow">{cables.length} matched</div>
    <div class="col-head"><span class="eyebrow">this copy</span><span class="name" title={other}>{rel(other, roots)}</span></div>
  </header>

  <div class="body" style:height={`${height}px`}>
    <ol class="col" style:--row={`${ROW}px`}>
      {#each left as t, i (t.path)}
        <li class:dim={!matchedLeft.has(i)} class:lit={hover?.i === i}>
          <span class="no mono">{t.track || '·'}</span>
          <span class="title" title={base(t.path)}>{title(t)}</span>
          <span class="dur mono">{time(t.duration)}</span>
          <Quality track={t} />
        </li>
      {/each}
    </ol>

    <svg class="cables" viewBox={`0 0 120 ${height}`} preserveAspectRatio="none" width="120" height={height} aria-hidden="true">
      {#each cables as c}
        <path d={path(c)} class:lit={hover === c} />
      {/each}
      {#each cables as c}
        <circle cx="3" cy={y(c.i)} r="3.2" class:lit={hover === c} />
        <circle cx="117" cy={y(c.j)} r="3.2" class:lit={hover === c} />
      {/each}
    </svg>

    <ol class="col" style:--row={`${ROW}px`}>
      {#each right as t, j (t.path)}
        {@const c = cables.find((x) => x.j === j)}
        <li class:dim={!matchedRight.has(j)} class:lit={hover?.j === j}>
          {#if c}
            <button class="listen" class:on={isPlaying(c)} onclick={() => listen(c)}
              aria-label={isPlaying(c) ? 'Pause' : `Play ${title(t)} and its kept copy`}>{isPlaying(c) ? '❚❚' : '▶'}</button>
            <button class="row" onmouseenter={() => (hover = c)} onmouseleave={() => (hover = null)}
              onfocus={() => (hover = c)} onblur={() => (hover = null)} onclick={() => open(c)}
              title="Compare these two tracks">
              <span class="no mono">{t.track || '·'}</span>
              <span class="title">{title(t)}</span>
              <span class="dur mono">{time(t.duration)}</span>
              <Quality track={t} />
            </button>
          {:else}
            <span class="no mono">{t.track || '·'}</span>
            <span class="title">{title(t)}</span>
            <span class="dur mono">{time(t.duration)}</span>
            <Quality track={t} />
          {/if}
        </li>
      {/each}
    </ol>
  </div>
  <p class="hint">▶ plays a track with its kept copy (switch with <kbd>1</kbd>/<kbd>2</kbd>). Click a track name for the full comparison with waveforms.</p>
</section>

<style>
  .bay { padding: 16px 18px 12px; }
  header, .body { display: grid; grid-template-columns: minmax(0, 1fr) 120px minmax(0, 1fr); }
  header { margin-bottom: 8px; align-items: end; }
  .col-head { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .col-head .name { font-size: 13px; color: var(--ink-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .col-head.keep .eyebrow { color: var(--keep); }
  .gutter-head { text-align: center; }

  .col { list-style: none; margin: 0; padding: 0; min-width: 0; }
  li, .row {
    height: var(--row); display: grid; grid-template-columns: 28px minmax(0, 1fr) auto auto; gap: 10px; align-items: center;
    padding: 0 8px; border-radius: 5px; font-size: 13.5px; transition: background .12s, opacity .12s;
  }
  li:has(.row) { padding: 0; display: grid; grid-template-columns: 30px minmax(0, 1fr); gap: 0; }
  .listen { all: unset; cursor: pointer; width: 26px; height: 26px; border-radius: 50%; display: grid; place-items: center;
    font-size: 10px; color: var(--ink-3); border: 1px solid var(--line); align-self: center; }
  .listen:hover, .listen.on { color: var(--accent-ink); background: var(--accent); border-color: var(--accent); }
  .listen:focus-visible { outline: 2px solid var(--accent); }
  .row { all: unset; box-sizing: border-box; width: 100%; height: var(--row); display: grid; grid-template-columns: 28px minmax(0, 1fr) auto auto; gap: 10px; align-items: center; padding: 0 8px; border-radius: 5px; cursor: pointer; }
  .row:focus-visible { outline: 2px solid var(--accent); }
  li.lit, li.lit .row { background: var(--accent-soft); }
  li.dim { opacity: .45; }
  .no { color: var(--ink-3); font-size: 11.5px; text-align: right; }
  .title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .dur { font-size: 11.5px; color: var(--ink-3); }

  .cables path { fill: none; stroke: var(--cable); stroke-width: 1.6; transition: stroke .12s, stroke-width .12s; }
  .cables path.lit { stroke: var(--accent); stroke-width: 3; }
  .cables circle { fill: var(--panel); stroke: var(--cable); stroke-width: 1.5; }
  .cables circle.lit { fill: var(--accent); stroke: var(--accent); }

  .hint { margin: 10px 0 0; font-size: 12px; color: var(--ink-3); }

  @media (max-width: 700px) {
    header, .body { grid-template-columns: minmax(0, 1fr) 40px minmax(0, 1fr); }
    .cables { width: 40px; }
    .dur { display: none; }
  }
</style>
