<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import { store } from '../lib/store.svelte.js';
  import { bytes, rel, artistAlbum, when } from '../lib/format.js';
  import Cover from './Cover.svelte';

  const plan = $derived(store.plan);
  const lib = $derived(plan.library || {});
  const nm = $derived(plan.new_music || { folders: [] });
  let scans = $state([]);

  onMount(async () => { try { scans = await api.scans(); } catch { /* history is optional */ } });
  $effect(() => { if (store.scan.state === 'done') api.scans().then((s) => (scans = s)).catch(() => {}); });

  const took = (sec) => (sec < 90 ? `${sec} s` : sec < 5400 ? `${Math.round(sec / 60)} min` : `${(sec / 3600).toFixed(1)} h`);

  function playtime(sec) {
    const h = Math.floor(sec / 3600);
    const d = Math.floor(h / 24);
    return d >= 2 ? `${d} days ${h % 24} h` : `${h} h ${Math.floor((sec % 3600) / 60)} min`;
  }
  const maxArtist = $derived(Math.max(1, ...(lib.top_artists || []).map((a) => a.bytes)));
  function bars(obj) {
    const total = Object.values(obj || {}).reduce((a, b) => a + b, 0) || 1;
    return Object.entries(obj || {}).map(([k, v]) => ({ k, v, pct: (v / total) * 100 }));
  }
</script>

<section class="lib rise">
  <header class="head">
    <div>
      <span class="eyebrow">your collection{plan.scan_seconds !== undefined ? ` · scanned in ${took(plan.scan_seconds)}` : ''}</span>
      <h1>Library</h1>
    </div>
  </header>

  <div class="tiles">
    {#each [
      ['tracks', (lib.tracks || 0).toLocaleString()],
      ['size', bytes(lib.bytes || 0)],
      ['playing time', playtime(lib.duration_seconds || 0)],
      ['artists', (lib.artists || 0).toLocaleString()],
      ['album folders', (lib.albums || 0).toLocaleString()],
    ] as [label, value], i}
      <div class="tile panel" style:animation-delay={`${i * 50}ms`}>
        <span class="eyebrow">{label}</span>
        <span class="value">{value}</span>
      </div>
    {/each}
  </div>

  <div class="grid">
    <article class="panel card new">
      <header>
        <h2>New music</h2>
        <span class="eyebrow">{nm.first_scan ? 'first scan' : `${nm.new_tracks} new · ${nm.changed_tracks} changed`}</span>
      </header>
      {#if nm.first_scan}
        <p class="muted">This was the first scan, so everything is new. From the next scan on, albums added or changed since the previous one appear here.</p>
      {:else if !nm.folders.length}
        <p class="muted">Nothing new since the previous scan.</p>
      {:else}
        <ul class="albums">
          {#each nm.folders.slice(0, 60) as f}
            {@const aa = artistAlbum(rel(f.folder, plan.roots))}
            <li>
              <Cover folder={f.folder} size={44} title={aa.album} />
              <span class="names"><span class="album">{aa.album}</span><span class="artist">{aa.artist}</span></span>
              <span class="tag mono">{f.new ? `${f.new} new` : ''}{f.new && f.changed ? ' · ' : ''}{f.changed ? `${f.changed} changed` : ''}</span>
            </li>
          {/each}
        </ul>
        {#if nm.folders.length > 60}<p class="muted">…and {nm.folders.length - 60} more.</p>{/if}
      {/if}
    </article>

    <article class="panel card">
      <header><h2>Formats</h2><span class="eyebrow">by track</span></header>
      {#each [['Lossless bit depth', lib.bit_depth], ['Lossless sample rate', lib.sample_rate], ['Lossy bitrate', lib.lossy_bitrate]] as [title, obj]}
        {#if Object.keys(obj || {}).length}
          <h3>{title}</h3>
          {#each bars(obj) as b}
            <div class="hbar">
              <span class="label">{b.k}</span>
              <span class="track"><span style:width={`${b.pct}%`}></span></span>
              <span class="mono num">{b.v.toLocaleString()}</span>
            </div>
          {/each}
        {/if}
      {/each}
    </article>

    <article class="panel card">
      <header><h2>Biggest artists</h2><span class="eyebrow">by size</span></header>
      {#each lib.top_artists || [] as a}
        <div class="hbar">
          <span class="label clip" title={a.artist}>{a.artist}</span>
          <span class="track"><span style:width={`${(a.bytes / maxArtist) * 100}%`}></span></span>
          <span class="mono num">{bytes(a.bytes)}</span>
        </div>
      {/each}
    </article>

    <article class="panel card">
      <header><h2>Largest albums</h2><span class="eyebrow">by size</span></header>
      <ul class="albums">
        {#each lib.largest_albums || [] as f}
          {@const aa = artistAlbum(rel(f.folder, plan.roots))}
          <li>
            <Cover folder={f.folder} size={36} title={aa.album} />
            <span class="names"><span class="album">{aa.album}</span><span class="artist">{aa.artist}</span></span>
            <span class="tag mono">{f.tracks} · {bytes(f.bytes)}</span>
          </li>
        {/each}
      </ul>
    </article>

    <article class="panel card wide">
      <header><h2>Scan history</h2><span class="eyebrow">{scans.length} scans</span></header>
      {#if scans.length}
        <div class="table" role="table">
          <div class="tr th" role="row">
            <span>When</span><span>Took</span><span>Tracks</span><span>New</span><span>Changed</span><span>Duplicate folders</span><span>Could free</span><span>Unreadable</span>
          </div>
          {#each scans as sc}
            <div class="tr" role="row">
              <span>{when(sc.time)}</span><span class="mono">{took(sc.seconds)}</span>
              <span class="mono">{sc.tracks.toLocaleString()}</span>
              <span class="mono">{sc.first_scan ? '—' : sc.new.toLocaleString()}</span>
              <span class="mono">{sc.first_scan ? '—' : sc.changed.toLocaleString()}</span>
              <span class="mono">{sc.duplicate_folders.toLocaleString()}</span>
              <span class="mono">{bytes(sc.bytes_to_free)}</span>
              <span class="mono">{sc.unreadable.toLocaleString()}</span>
            </div>
          {/each}
        </div>
      {:else}
        <p class="muted">Scans run from the dashboard or the command line are listed here.</p>
      {/if}
    </article>
  </div>
</section>

<style>
  .head { margin-bottom: 18px; }
  h1 { font-size: 44px; font-weight: 520; margin-top: 4px; }
  .tiles { display: grid; grid-template-columns: repeat(5, 1fr); gap: 14px; margin-bottom: 18px; }
  .tile { padding: 14px 16px; display: flex; flex-direction: column; gap: 6px; animation: rise .5s var(--ease) both; }
  .value { font-family: var(--font-display); font-size: 30px; line-height: 1.05; }
  .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
  .card { padding: 18px 20px; min-width: 0; }
  .card.new { grid-row: span 2; }
  .card.wide { grid-column: 1 / -1; }
  .card header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 10px; gap: 10px; }
  h2 { font-size: 21px; }
  h3 { font-family: var(--font-mono); font-size: 11px; letter-spacing: .12em; text-transform: uppercase; color: var(--ink-3); margin: 14px 0 6px; font-weight: 400; }
  .muted { color: var(--ink-3); font-size: 13.5px; }
  .hbar { display: grid; grid-template-columns: 150px minmax(0, 1fr) 80px; gap: 10px; align-items: center; font-size: 13.5px; padding: 3px 0; }
  .hbar .track { height: 8px; border-radius: 4px; background: var(--line-soft); overflow: hidden; }
  .hbar .track span { display: block; height: 100%; background: var(--accent); border-radius: 4px; }
  .num { text-align: right; font-size: 12px; color: var(--ink-2); }
  .clip, .album, .artist { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .albums { list-style: none; margin: 0; padding: 0; }
  .albums li { display: flex; align-items: center; gap: 12px; padding: 6px 0; border-bottom: 1px solid var(--line-soft); min-width: 0; }
  .names { flex: 1; min-width: 0; display: flex; flex-direction: column; }
  .album { font-size: 14px; }
  .artist { font-size: 12px; color: var(--ink-3); }
  .tag { font-size: 11.5px; color: var(--accent); white-space: nowrap; }
  .tr { display: grid; grid-template-columns: 1.6fr repeat(7, 1fr); gap: 10px; padding: 6px 4px; font-size: 13px; border-bottom: 1px solid var(--line-soft); }
  .tr.th { font-family: var(--font-mono); font-size: 10.5px; letter-spacing: .1em; text-transform: uppercase; color: var(--ink-3); }
  @media (max-width: 1000px) {
    .tiles { grid-template-columns: repeat(2, 1fr); }
    .grid { grid-template-columns: 1fr; }
    .card.new { grid-row: auto; }
    .tr { grid-template-columns: 1.4fr repeat(3, 1fr); }
    .tr > :nth-child(n+5) { display: none; }
  }
</style>
