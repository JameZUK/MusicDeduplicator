<script>
  // Two copies on one timeline: waveform A above, B mirrored below, the difference strip
  // between them. Click a waveform to hear that copy from there; A/B switching is instant
  // because both play together (see player.svelte.js).
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import { store } from '../lib/store.svelte.js';
  import { player, load, setOffset, toggle, switchTo, seek, setAutoFlip } from '../lib/player.svelte.js';
  import { waveOf } from '../lib/waves.svelte.js';
  import { barCount, windowBars, barsPath } from '../lib/waveform.js';
  import { rel, base, dir, time } from '../lib/format.js';
  import Quality from './Quality.svelte';

  let { a, b, onclose } = $props();

  let profile = $state(null);
  let tracks = $state({});
  let error = $state('');
  let zoom = $state('all');       // all | follow | diff
  let loop = $state(false);
  let width = $state(0);
  const LANE = 74;

  onMount(() => {
    load(a, b, { labelA: base(dir(a)), labelB: base(dir(b)), offset: 0 });
    api.compare(a, b).then((p) => { profile = p; setOffset(p.offset_seconds || 0); })
      .catch((e) => (error = e.message));
    for (const p of [a, b]) {
      api.folder(dir(p)).then((f) => (tracks = { ...tracks, [p]: f.tracks.find((t) => t.path === p) })).catch(() => {});
    }
  });

  const waveA = $derived(waveOf(a));
  const waveB = $derived(waveOf(b));
  const offset = $derived(profile?.offset_seconds ?? 0);
  const total = $derived(Math.max(waveA?.data?.duration || 0, (waveB?.data?.duration || 0) + offset, player.duration || 0, 1));

  const worst = $derived.by(() => {
    if (!profile?.windows?.length) return null;
    const i = profile.windows.indexOf(Math.max(...profile.windows));
    return profile.start_seconds + i * profile.window_seconds;
  });

  const view = $derived.by(() => {
    if (zoom === 'diff' && worst !== null) return clampWindow(worst - 10, worst + 12);
    if (zoom === 'follow') {
      const t0 = Math.floor(player.position / 25) * 25 - 2.5;
      return clampWindow(t0, t0 + 30);
    }
    return [0, total];
  });
  function clampWindow(t0, t1) {
    const len = t1 - t0;
    const s = Math.max(0, Math.min(t0, total - len));
    return [s, Math.min(total, s + len)];
  }

  const count = $derived(barCount(width, zoom === 'all' ? 3 : 4));
  const barsA = $derived(waveA?.status === 'ready' ? windowBars(waveA.data.peak, waveA.data.per_second, view[0], view[1], count) : []);
  const barsB = $derived(waveB?.status === 'ready' ? windowBars(waveB.data.peak, waveB.data.per_second, view[0] - offset, view[1] - offset, count) : []);
  const pathA = $derived(barsPath(barsA, Math.max(width, 1), LANE, { anchor: 'bottom', minHeight: 1 }));
  const pathB = $derived(barsPath(barsB, Math.max(width, 1), LANE, { anchor: 'top', minHeight: 1 }));

  const x = (t) => ((t - view[0]) / (view[1] - view[0])) * width;
  const tAt = (event) => {
    const box = event.currentTarget.getBoundingClientRect();
    return view[0] + ((event.clientX - box.left) / box.width) * (view[1] - view[0]);
  };

  const cells = $derived.by(() => {
    if (!profile?.windows) return [];
    const ws = profile.window_seconds;
    return profile.windows.map((v, i) => ({ v, t: profile.start_seconds + i * ws, ws }))
      .filter((c) => c.t + c.ws > view[0] && c.t < view[1]);
  });

  function colour(v) {
    const th = profile.thresholds;
    if (v <= th.same_max_ber) return 'var(--keep)';
    if (v <= th.same_max_window_ber) return 'var(--accent)';
    return 'var(--hot)';
  }
  const alpha = (v) => Math.min(1, 0.35 + v * 2.2);

  const verdict = $derived({
    same: ['Same audio', 'Copies of one recording; any difference is just the encoding.'],
    variant: ['Edited version', 'Mostly identical but changed somewhere. Listen at the red stretch.'],
    different: ['Different', 'Too different to be the same recording.'],
  }[profile?.kind] ?? ['Comparing…', '']);

  // Loop the few seconds around the biggest difference.
  $effect(() => {
    if (!loop || worst === null || !player.playing) return;
    const s = Math.max(0, worst - 3), e = worst + 5;
    if (player.position > e || player.position < s - 1) seek(s);
  });

  function jumpToDifference() {
    if (worst === null) return;
    zoom = 'diff';
    seek(Math.max(0, worst - 3));
  }

  function onkey(e) {
    if (e.target instanceof Element && e.target.closest('input, textarea, select')) return;
    const k = e.key.toLowerCase();
    if (e.key === ' ') { toggle(); e.preventDefault(); }
    else if (k === 'a' || k === '1') switchTo('a');
    else if (k === 'b' || k === '2') switchTo('b');
    else if (k === 'x') switchTo(player.active === 'a' ? 'b' : 'a');
    else if (e.key === 'Escape' && onclose) onclose();
  }
</script>

<svelte:window onkeydown={onkey} />

<article class="compare">
  <header class="head">
    <div>
      <span class="eyebrow">track comparison</span>
      <h1>{verdict[0]}</h1>
      <p class="sub">{verdict[1]}</p>
    </div>
    {#if profile && profile.kind !== 'different'}
      <dl class="stats mono">
        <div><dt>overall</dt><dd>{(profile.ber * 100).toFixed(1)}%</dd></div>
        <div><dt>worst 2.5 s</dt><dd class:hot={profile.max_window_ber > profile.thresholds.same_max_window_ber}>{(profile.max_window_ber * 100).toFixed(1)}%</dd></div>
        <div><dt>offset</dt><dd>{offset >= 0 ? '+' : ''}{offset.toFixed(2)} s</dd></div>
      </dl>
    {/if}
    {#if onclose}<button class="btn close" onclick={onclose} aria-label="Close comparison">✕ <kbd>Esc</kbd></button>{/if}
  </header>

  {#if error}<p class="err">{error}</p>{/if}

  <section class="stage panel">
    <div class="toolbar">
      <div class="zoom" role="radiogroup" aria-label="Zoom">
        {#each [['all', 'Whole track'], ['follow', 'Follow 30 s'], ['diff', 'Around the difference']] as [k, label]}
          <button role="radio" aria-checked={zoom === k} class:on={zoom === k} disabled={k === 'diff' && worst === null}
            onclick={() => (zoom = k)}>{label}</button>
        {/each}
      </div>
      <span class="mono range">{time(view[0])} – {time(view[1])}</span>
    </div>

    <div class="lanes" bind:clientWidth={width}>
      {#each [['a', a, pathA, waveA], ['b', b, pathB, waveB]] as [key, path, d, wave]}
        {@const t = tracks[path]}
        <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
        <div class={`lane ${key}`} class:active={player.active === key} style:height={`${LANE}px`}
          onclick={(e) => { seek(tAt(e), key); }} title={`Click to hear ${key.toUpperCase()} from here`}>
          <span class="tag"><b>{key.toUpperCase()}</b>
            <span class="name">{t?.title || base(path)}</span>
            <Quality track={t} />
            <span class="where">{rel(dir(path), store.plan.roots)}</span>
          </span>
          {#if d}
            <svg width={width} height={LANE} viewBox={`0 0 ${width} ${LANE}`} aria-hidden="true"><path d={d} /></svg>
          {:else if wave?.status === 'error'}
            <span class="note">{wave.error}</span>
          {:else}
            <span class="note">drawing waveform…</span>
          {/if}
        </div>
        {#if key === 'a'}
          <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
          <div class="diff" onclick={(e) => seek(tAt(e))} title="Difference between A and B over time">
            {#each cells as c}
              <span style:left={`${x(c.t)}px`} style:width={`${Math.max(1, x(c.t + c.ws) - x(c.t) - 1)}px`}
                style:background={colour(c.v)} style:opacity={alpha(c.v)}
                title={`${time(c.t)}: ${(c.v * 100).toFixed(0)}% different`}></span>
            {/each}
          </div>
        {/if}
      {/each}
      {#if player.position >= view[0] && player.position <= view[1]}
        <i class="playhead" style:left={`${x(player.position)}px`}></i>
      {/if}
    </div>

    <div class="legend">
      <span><i style:background="var(--keep)"></i>same</span>
      <span><i style:background="var(--accent)"></i>slight</span>
      <span><i style:background="var(--hot)"></i>different</span>
      <span class="hint">Click a waveform to hear that copy from there</span>
    </div>
  </section>

  <section class="transport panel">
    <button class="btn primary play" onclick={toggle} aria-label={player.playing ? 'Pause' : 'Play'}>
      {#if player.playing}
        <svg viewBox="0 0 16 16"><rect x="3" y="2" width="3.5" height="12" rx="1" /><rect x="9.5" y="2" width="3.5" height="12" rx="1" /></svg>
      {:else}
        <svg viewBox="0 0 16 16"><path d="M4 2.5v11l9-5.5z" /></svg>
      {/if}
    </button>
    <div class="ab" role="radiogroup" aria-label="Which copy you hear">
      <button role="radio" aria-checked={player.active === 'a'} class:on={player.active === 'a'} onclick={() => switchTo('a')}>A</button>
      <button role="radio" aria-checked={player.active === 'b'} class:on={player.active === 'b'} onclick={() => switchTo('b')}>B</button>
    </div>
    <span class="clock mono">{time(player.position)}</span>
    {#if player.status === 'loading'}
      <span class="prep mono">preparing A/B… {Math.round(player.progress * 100)}%</span>
    {/if}
    <label class="opt">
      <span class="eyebrow">auto A/B</span>
      <select value={player.autoFlip} onchange={(e) => setAutoFlip(Number(e.currentTarget.value))}>
        <option value={0}>off</option><option value={2}>every 2 s</option><option value={4}>every 4 s</option><option value={8}>every 8 s</option>
      </select>
    </label>
    {#if worst !== null && profile?.kind === 'variant'}
      <button class="btn" onclick={jumpToDifference}>Jump to the difference</button>
      <label class="opt check"><input type="checkbox" bind:checked={loop} /> loop it</label>
    {/if}
    <span class="tip"><kbd>Space</kbd> play <kbd>A</kbd>/<kbd>B</kbd> or <kbd>X</kbd> switch instantly</span>
    {#if player.error}<span class="err">{player.error}</span>{/if}
  </section>
</article>

<style>
  .head { display: grid; grid-template-columns: 1fr auto auto; gap: 24px; align-items: end; margin-bottom: 16px; }
  h1 { font-size: clamp(28px, 3.4vw, 44px); margin: 4px 0 2px; font-weight: 520; }
  .sub { margin: 0; color: var(--ink-2); }
  .stats { display: flex; gap: 22px; margin: 0; }
  .stats div { display: flex; flex-direction: column; align-items: flex-end; }
  dt { font-size: 10.5px; color: var(--ink-3); text-transform: uppercase; letter-spacing: .12em; }
  dd { margin: 0; font-size: 20px; }
  dd.hot { color: var(--hot); }
  .close { align-self: start; }
  .err { color: var(--remove); }

  .stage { padding: 12px 16px 12px; margin-bottom: 14px; }
  .toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; gap: 12px; flex-wrap: wrap; }
  .zoom { display: flex; gap: 4px; }
  .zoom button { border: 1px solid var(--line-soft); background: none; border-radius: 999px; padding: 3px 10px; font-size: 12.5px; color: var(--ink-2); }
  .zoom button.on { border-color: var(--accent); color: var(--ink); background: var(--accent-soft); }
  .zoom button:disabled { opacity: .4; cursor: not-allowed; }
  .range { font-size: 12px; color: var(--ink-3); }

  .lanes { position: relative; user-select: none; }
  .lane { position: relative; cursor: pointer; border-radius: 6px; transition: background .15s; }
  .lane:hover { background: var(--panel-2); }
  .lane svg { position: absolute; inset: 0; display: block; }
  .lane path { fill: var(--ink-3); opacity: .5; transition: fill .15s, opacity .15s; }
  .lane.active path { fill: var(--accent); opacity: .95; }
  .tag { position: absolute; left: 8px; z-index: 1; display: flex; gap: 8px; align-items: center; font-size: 12px; max-width: calc(100% - 16px);
    background: color-mix(in srgb, var(--panel) 80%, transparent); padding: 2px 8px 2px 4px; border-radius: 5px; pointer-events: none; }
  .lane.a .tag { top: 4px; }
  .lane.b .tag { bottom: 4px; }
  .tag b { font-family: var(--font-display); font-size: 16px; color: var(--ink-3); }
  .lane.active .tag b { color: var(--accent); }
  .tag .name { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .tag .where { color: var(--ink-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .note { position: absolute; inset: 0; display: grid; place-items: center; font-size: 12px; color: var(--ink-3); }

  .diff { position: relative; height: 22px; margin: 3px 0; cursor: crosshair; border-radius: 3px; background: var(--panel-2); overflow: hidden; }
  .diff span { position: absolute; top: 0; bottom: 0; }
  .playhead { position: absolute; top: 0; bottom: 0; width: 2px; margin-left: -1px; background: var(--ink); box-shadow: 0 0 10px var(--ink); pointer-events: none; transition: left .25s linear; }

  .legend { display: flex; gap: 16px; align-items: center; margin-top: 10px; font-size: 12px; color: var(--ink-3); flex-wrap: wrap; }
  .legend i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 6px; vertical-align: -1px; }
  .hint { margin-left: auto; }

  .transport { display: flex; align-items: center; gap: 16px; padding: 12px 16px; flex-wrap: wrap; }
  .play { width: 48px; height: 48px; padding: 0; justify-content: center; border-radius: 50%; }
  .play svg { width: 16px; height: 16px; fill: currentColor; }
  .ab { display: flex; border: 1px solid var(--line); border-radius: 999px; overflow: hidden; }
  .ab button { border: 0; background: none; padding: 6px 18px; font-family: var(--font-display); font-size: 19px; color: var(--ink-3); }
  .ab button.on { background: var(--accent); color: var(--accent-ink); }
  .clock { font-size: 22px; min-width: 64px; }
  .prep { font-size: 12px; color: var(--accent); }
  .opt { display: flex; flex-direction: column; gap: 2px; font-size: 13px; }
  .opt.check { flex-direction: row; align-items: center; gap: 6px; }
  .opt input { accent-color: var(--accent); }
  select { background: var(--panel-2); color: var(--ink); border: 1px solid var(--line); border-radius: 6px; font: inherit; font-size: 12.5px; padding: 2px 4px; }
  .tip { margin-left: auto; font-size: 12px; color: var(--ink-3); }

  @media (max-width: 760px) {
    .head { grid-template-columns: 1fr auto; }
    .stats { grid-column: 1 / -1; grid-row: 2; justify-content: flex-start; }
    .stats div { align-items: flex-start; }
    .tag .where, .tip, .hint { display: none; }
  }
</style>
