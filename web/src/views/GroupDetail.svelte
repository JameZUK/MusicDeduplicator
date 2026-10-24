<script>
  import { api } from '../lib/api.js';
  import { route, setQuery } from '../lib/router.svelte.js';
  import { store, decide, decisionOf, decisionKind } from '../lib/store.svelte.js';
  import { bytes, rel, artistAlbum } from '../lib/format.js';
  import Cover from './Cover.svelte';
  import Quality from './Quality.svelte';
  import PatchBay from './PatchBay.svelte';

  let { group, onchoose } = $props();

  let detail = $state(null);
  let error = $state('');
  // Which copy the patch bay shows is in the URL, so Back and reloads return to it.
  const selected = $derived(group.remove.some((r) => r.folder === route.query.copy)
    ? route.query.copy : group.remove[0]?.folder ?? null);

  $effect(() => {
    api.group(group.id).then((d) => (detail = d)).catch((e) => (error = e.message));
  });

  const plan = $derived(store.plan);
  const kind = $derived(decisionKind(group));
  const choice = $derived(decisionOf(group));
  const keeper = $derived(choice && typeof choice === 'object' ? choice.keep : group.keep);
  const members = $derived([
    { folder: group.keep, kind: 'original' },
    ...group.remove,
  ]);

  function summary(folder) {
    const f = detail?.folders[folder];
    if (!f) return null;
    const best = [...f.tracks].sort((a, b) => score(b) - score(a))[0];
    return {
      tracks: f.tracks.length,
      size: f.tracks.reduce((n, t) => n + t.size, 0),
      best,
      release: f.release,
      formats: [...new Set(f.tracks.map((t) => t.path.split('.').pop().toLowerCase()))].join(' + '),
    };
  }
  function score(t) {
    return t.lossless ? 1e12 + (t.bits || 16) * 1e9 + (t.sample_rate || 0) : t.bitrate || 0;
  }
</script>

<article class="group rise">
  <header class="head">
    <div>
      <span class="eyebrow">group {group.id} · {members.length} copies · {bytes(group.bytes)} reclaimable</span>
      <h1>{artistAlbum(rel(group.keep, plan.roots)).album}</h1>
      <p class="sub">{artistAlbum(rel(group.keep, plan.roots)).artist || 'Unknown artist'}</p>
    </div>
    <div class="actions">
      {#if kind !== 'undecided'}
        <span class={`verdict ${kind}`}>
          {kind === 'accept' ? 'Accepted' : kind === 'skip' ? 'Skipped' : 'New keeper chosen'}
        </span>
        <button class="btn" onclick={() => decide(group.id, null)}>Undo <kbd>U</kbd></button>
      {/if}
      <button class="btn" onclick={() => onchoose('skip')}>Keep all <kbd>S</kbd></button>
      <button class="btn primary" onclick={() => onchoose('accept')}>Accept <kbd>A</kbd></button>
    </div>
  </header>

  {#if error}<p class="err">{error}</p>{/if}

  <div class="cards">
    {#each members as m (m.folder)}
      {@const s = summary(m.folder)}
      {@const isKeeper = m.folder === keeper}
      {@const aa = artistAlbum(rel(m.folder, plan.roots))}
      <div class="card panel" class:keeper={isKeeper} class:selected={m.folder === selected && !isKeeper}>
        <span class="stamp">{isKeeper ? 'keep' : 'remove'}</span>
        <div class="top">
          <Cover folder={m.folder} size={72} title={aa.album} />
          <div class="info">
            <span class="path" title={m.folder}>{rel(m.folder, plan.roots)}</span>
            {#if s}
              <span class="line"><Quality track={s.best} /> <span class="mono dim">{s.formats}</span></span>
              <span class="line mono dim">{s.tracks} tracks · {bytes(s.size)} · {s.release}</span>
            {/if}
          </div>
        </div>
        <div class="foot">
          {#if m.kind === 'contained'}
            <span class="note">tracks all in the kept copy</span>
          {:else if m.kind === 'original'}
            <span class="note">{isKeeper ? 'best copy found' : 'original choice'}</span>
          {:else}
            <span class="note">same album</span>
          {/if}
          {#if !isKeeper}
            {#if m.folder !== group.keep}
              <button class="btn tiny" onclick={() => setQuery({ copy: m.folder })}>Show tracks</button>
            {/if}
            {#if m.kind !== 'contained'}
              <button class="btn tiny keep" onclick={() => decide(group.id, { keep: m.folder })}>Keep this instead</button>
            {/if}
          {/if}
        </div>
      </div>
    {/each}
  </div>

  {#if detail && selected}
    <PatchBay {detail} keep={group.keep} other={selected} roots={plan.roots} />
  {:else if !detail}
    <div class="panel loading"><span class="eyebrow">loading tracks…</span></div>
  {/if}
</article>

<style>
  .head { display: flex; justify-content: space-between; gap: 20px; align-items: flex-end; margin-bottom: 18px; flex-wrap: wrap; }
  h1 { font-size: clamp(26px, 3.2vw, 40px); line-height: 1.05; margin: 6px 0 2px; font-weight: 520; }
  .sub { margin: 0; color: var(--ink-2); font-size: 16px; }
  .actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .verdict { font-family: var(--font-mono); font-size: 12px; padding: 4px 8px; border-radius: 4px; }
  .verdict.accept { color: var(--keep); background: var(--keep-soft); }
  .verdict.skip { color: var(--skip); border: 1px solid var(--line); }
  .verdict.changed { color: var(--accent); background: var(--accent-soft); }
  .err { color: var(--remove); }

  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(270px, 1fr)); gap: 14px; margin-bottom: 20px; }
  .card { position: relative; padding: 14px; display: flex; flex-direction: column; gap: 12px; border-color: var(--line); transition: border-color .2s, transform .2s; }
  .card.keeper { border-color: var(--keep); background: linear-gradient(160deg, var(--keep-soft), var(--panel) 55%); }
  .card:not(.keeper) { background: linear-gradient(160deg, var(--remove-soft), var(--panel) 45%); }
  .card.selected { border-color: var(--accent); }
  .stamp {
    position: absolute; top: 10px; right: 12px; font-family: var(--font-mono); font-size: 10px;
    letter-spacing: .18em; text-transform: uppercase; padding: 3px 6px; border-radius: 3px; transform: rotate(3deg);
    color: var(--remove); border: 1.5px solid currentColor;
  }
  .keeper .stamp { color: var(--keep); transform: rotate(-3deg); }
  .top { display: flex; gap: 12px; min-width: 0; }
  .info { min-width: 0; display: flex; flex-direction: column; gap: 6px; padding-right: 72px; }
  .path { font-size: 13.5px; overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; word-break: break-word; }
  .line { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; font-size: 12px; }
  .dim { color: var(--ink-3); }
  .foot { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: auto; }
  .note { font-size: 12px; color: var(--ink-3); margin-right: auto; }
  .btn.tiny { font-size: 12px; padding: 3px 9px; }
  .loading { padding: 30px; text-align: center; }
</style>
