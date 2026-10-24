<script>
  import { store, decidedBytes, decisionKind, toggleWithin } from '../lib/store.svelte.js';
  import { go, openCompare } from '../lib/router.svelte.js';
  import { bytes, rel, base } from '../lib/format.js';

  const plan = $derived(store.plan);
  const s = $derived(plan.summary);
  const r = (p) => rel(p, plan.roots);

  const tiers = [
    ['hi-res', 'Hi-res', 'var(--accent)'],
    ['cd', 'CD quality', 'var(--keep)'],
    ['lossy', 'Lossy', 'var(--ink-3)'],
    ['unknown', 'Unknown', 'var(--line)'],
  ];
  const qualityTotal = $derived(Object.values(s.quality || {}).reduce((a, b) => a + b, 0) || 1);
  const undecided = $derived(plan.groups.filter((g) => decisionKind(g) === 'undecided').length);
  const planned = $derived(s.bytes_to_free || 0);
  const decided = $derived(decidedBytes(plan));
  const within = $derived(plan.within_folder || []);
  const canActOnWithin = $derived(plan.options?.within_folders);
</script>

<section class="hero rise">
  <div class="intro">
    <span class="eyebrow">plan from {new Date(plan.created.replace(/([+-]\d{2})(\d{2})$/, '$1:$2')).toLocaleString()}</span>
    <h1>
      {s.audio_files.toLocaleString()} tracks,
      <em>{bytes(s.audio_bytes)}</em>
    </h1>
    <p class="lede">
      {s.duplicate_folders.toLocaleString()} folders hold copies of music you already have elsewhere.
      Reviewing them frees up to <strong class="mono">{bytes(planned)}</strong>.
    </p>
    <div class="cta">
      <button class="btn primary" onclick={() => go('review')}>
        {undecided ? `Review ${undecided} group${undecided === 1 ? '' : 's'}` : 'Revisit decisions'}
      </button>
      <span class="eyebrow">{plan.groups.length - undecided} decided · {bytes(decided)} selected</span>
    </div>
  </div>

  <div class="meter panel" aria-label={`Reclaimable: ${bytes(planned)}, of which ${bytes(decided)} selected`}>
    <div class="meter-head">
      <span class="eyebrow">reclaimable</span>
      <span class="meter-total mono">{bytes(planned)}</span>
    </div>
    <!-- Every segment is a share of the reclaimable space: soft amber until you accept
         the groups it stands for, then green. -->
    <div class="vu">
      {#each Array(24) as _, i}
        <span class:planned={planned > 0} class:lit={planned && i < Math.round((decided / planned) * 24)}></span>
      {/each}
    </div>
    <div class="vu-legend mono">
      <span><i class="sw lit"></i>{bytes(decided)} selected</span>
      <span>{s.audio_bytes ? `${((planned / s.audio_bytes) * 100).toFixed(1)}% of your library` : ''}</span>
    </div>
  </div>
</section>

<section class="grid">
  <article class="panel card wide rise" style:animation-delay="60ms">
    <header><h2>Quality</h2><span class="eyebrow">by track</span></header>
    <div class="spectrum" role="img" aria-label="Share of tracks by quality">
      {#each tiers as [key, label, colour]}
        {#if s.quality?.[key]}
          <span style:flex={s.quality[key]} style:background={colour} title={`${label}: ${s.quality[key]}`}></span>
        {/if}
      {/each}
    </div>
    <ul class="legend">
      {#each tiers as [key, label, colour]}
        {#if s.quality?.[key]}
          <li><i style:background={colour}></i>{label}
            <span class="mono">{s.quality[key].toLocaleString()} · {Math.round((s.quality[key] / qualityTotal) * 100)}%</span></li>
        {/if}
      {/each}
    </ul>
    <div class="formats">
      {#each Object.entries(s.formats || {}) as [ext, n]}
        <span class="chip mono">{ext} <b>{n.toLocaleString()}</b></span>
      {/each}
    </div>
  </article>

  {#if plan.new_music && !plan.new_music.first_scan}
    <article class="panel card wide rise new" style:animation-delay="90ms">
      <header><h2>New since the last scan</h2>
        <span class="eyebrow">{plan.new_music.new_tracks} new · {plan.new_music.changed_tracks} changed</span></header>
      {#if plan.new_music.folders.length}
        <p class="muted">{plan.new_music.folders.length} album folder{plan.new_music.folders.length === 1 ? '' : 's'} with new or changed tracks.
          <button class="link inline" onclick={() => go('library')}>See them in Library →</button></p>
      {:else}
        <p class="muted">Nothing new since the previous scan.</p>
      {/if}
    </article>
  {/if}

  <article class="panel card rise" style:animation-delay="120ms">
    <header><h2>Kept intact</h2><span class="eyebrow">never touched</span></header>
    <p class="muted">Releases that share audio but are distinct, so nothing in them is removed.</p>
    <dl>
      <div><dt>Smaller editions inside a bigger one</dt><dd class="mono">{plan.smaller_editions_kept.length}</dd></div>
      <div><dt>Tracks a release repeats on purpose</dt><dd class="mono">{plan.repeated_in_release.length}</dd></div>
      <div><dt>Copies blocked by unreadable files</dt><dd class="mono">{plan.blocked.length}</dd></div>
    </dl>
    {#if plan.smaller_editions_kept.length}
      <ul class="list">
        {#each plan.smaller_editions_kept.slice(0, 5) as e}
          <li><span class="clip">{r(e.folder)}</span><span class="tag">{e.edition} ⊂ {e.contained_in_edition}</span></li>
        {/each}
      </ul>
    {/if}
  </article>

  <article class="panel card rise" style:animation-delay="180ms">
    <header><h2>Similar versions</h2><span class="eyebrow">{plan.edited_versions.length}</span></header>
    <p class="muted">Same recording, different somewhere: explicit and clean edits, remasters, alternate mixes. Never treated as duplicates; compare and listen to see where.</p>
    <ul class="list">
      {#each plan.edited_versions.slice(0, 8) as v}
        <li>
          <button class="link" onclick={() => openCompare(v.paths[0], v.paths[1])}>
            <span class="clip">{base(v.paths[0])}</span>
          </button>
          <span class="tag mono">@{v.differs_at}</span>
        </li>
      {:else}
        <li class="muted">None found.</li>
      {/each}
    </ul>
  </article>

  <article class="panel card rise" style:animation-delay="240ms">
    <header><h2>Couldn't read</h2><span class="eyebrow">{plan.unreadable.length} files</span></header>
    <p class="muted">Possibly corrupt. A folder containing any of these is never removed.
      {#if plan.damaged?.length}<br />Another <strong>{plan.damaged.length.toLocaleString()}</strong> are damaged but playable
        (a glitch somewhere, marked ⚠). Where there's a copy, the clean one is kept.{/if}</p>
    <ul class="list">
      {#each plan.unreadable.slice(0, 8) as u}
        <li title={u.error}><span class="clip">{r(u.path)}</span></li>
      {:else}
        <li class="muted">Every file was readable.</li>
      {/each}
    </ul>
    {#if plan.unreadable.length > 8}<p class="muted more">…and {plan.unreadable.length - 8} more in the plan file.</p>{/if}
  </article>

  <article class="panel card rise" style:animation-delay="300ms">
    <header><h2>Copies inside a folder</h2><span class="eyebrow">{within.length}</span></header>
    <p class="muted">
      {canActOnWithin ? 'Tick the extra copies you want removed.' : 'Reported only. Rescan with --within-folders to act on these.'}
    </p>
    <ul class="list">
      {#each within.slice(0, 10) as w}
        <li>
          {#if canActOnWithin}
            <input type="checkbox" checked={store.decisions.within.includes(w.remove.path)}
              onchange={(e) => toggleWithin(w.remove.path, e.currentTarget.checked)}
              aria-label={`Remove ${base(w.remove.path)}`} />
          {/if}
          <span class="clip" title={r(w.remove.path)}>{base(w.remove.path)}</span>
          <span class="tag">= {base(w.keep.path)}</span>
        </li>
      {:else}
        <li class="muted">None found.</li>
      {/each}
    </ul>
  </article>

  <article class="panel card rise" style:animation-delay="360ms">
    <header><h2>Shared tracks</h2><span class="eyebrow">{plan.shared_tracks.length} pairs</span></header>
    <p class="muted">Folders that overlap but are both kept: compilations, deluxe editions, partial copies.</p>
    <ul class="list">
      {#each plan.shared_tracks.slice(0, 6) as x}
        <li><span class="clip">{r(x.folders[0])}</span><span class="tag mono">{x.shared_tracks}/{x.tracks[0]}</span></li>
      {/each}
    </ul>
  </article>
</section>

<style>
  .hero { display: grid; grid-template-columns: 1fr 340px; gap: 32px; align-items: end; margin-bottom: 30px; }
  h1 { font-size: clamp(34px, 5vw, 60px); line-height: 1.02; margin: 10px 0 14px; font-weight: 500; }
  h1 em { color: var(--accent); font-style: italic; }
  .lede { max-width: 60ch; color: var(--ink-2); font-size: 17px; margin: 0 0 20px; }
  .lede strong { color: var(--ink); }
  .cta { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }

  .meter { padding: 18px 20px; }
  .vu { display: grid; grid-template-columns: repeat(24, 1fr); gap: 3px; margin: 12px 0 8px; height: 46px; }
  .vu span { background: var(--line-soft); border-radius: 2px; transition: background .4s; }
  .vu span.planned { background: var(--accent-soft); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 35%, transparent); }
  .vu span.lit { background: var(--keep); box-shadow: none; }
  .vu-legend { display: flex; justify-content: space-between; gap: 10px; font-size: 12px; color: var(--ink-3); flex-wrap: wrap; }
  .meter-head { display: flex; justify-content: space-between; align-items: baseline; }
  .meter-total { font-size: 20px; color: var(--accent); }
  .sw { display: inline-block; width: 9px; height: 9px; border-radius: 2px; margin-right: 6px; vertical-align: -1px; }
  .sw.lit { background: var(--keep); }

  .grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; }
  .card { padding: 18px 20px; min-width: 0; }
  .card.wide { grid-column: span 3; }
  .card header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px; }
  h2 { font-size: 21px; }
  .muted { color: var(--ink-3); font-size: 13.5px; margin: 0 0 10px; }
  .more { margin-top: 8px; }

  .spectrum { display: flex; height: 14px; border-radius: 999px; overflow: hidden; gap: 2px; margin: 10px 0 14px; }
  .legend { list-style: none; padding: 0; margin: 0 0 14px; display: flex; gap: 22px; flex-wrap: wrap; font-size: 14px; }
  .legend i { display: inline-block; width: 9px; height: 9px; border-radius: 2px; margin-right: 7px; }
  .legend .mono { color: var(--ink-3); margin-left: 6px; font-size: 12px; }
  .formats { display: flex; gap: 8px; flex-wrap: wrap; }
  .chip { font-size: 12px; padding: 3px 9px; border-radius: 999px; border: 1px solid var(--line); color: var(--ink-2); }
  .chip b { color: var(--ink); font-weight: 500; margin-left: 4px; }

  dl { margin: 0 0 12px; }
  dl div { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px dashed var(--line-soft); font-size: 14px; }
  dd { margin: 0; color: var(--accent); }

  .list { list-style: none; margin: 0; padding: 0; font-size: 13.5px; }
  .list li { display: flex; align-items: center; gap: 8px; padding: 5px 0; border-bottom: 1px solid var(--line-soft); min-width: 0; }
  .list li:last-child { border-bottom: 0; }
  .clip { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .tag { flex: 0 1 auto; max-width: 50%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    font-size: 11.5px; color: var(--ink-3); }
  .link { all: unset; flex: 1; min-width: 0; display: flex; cursor: pointer; color: var(--ink); text-decoration: underline; text-decoration-color: var(--line); text-underline-offset: 3px; }
  .link:hover { text-decoration-color: var(--accent); }
  .link.inline { display: inline; flex: none; margin-left: 6px; }
  input[type='checkbox'] { accent-color: var(--accent); }

  @media (max-width: 1000px) {
    .hero { grid-template-columns: 1fr; }
    .grid { grid-template-columns: 1fr 1fr; }
    .card.wide { grid-column: span 2; }
  }
  @media (max-width: 640px) {
    .grid { grid-template-columns: 1fr; }
    .card.wide { grid-column: span 1; }
  }
</style>
