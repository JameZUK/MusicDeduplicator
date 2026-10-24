<script>
  // A waveform seek bar for the player. As in Lyrion Anywhere's SeekBar, the control is a
  // native range input laid over the drawing, so keyboard, touch and screen readers work.
  import { player, seek } from '../lib/player.svelte.js';
  import { waveOf } from '../lib/waves.svelte.js';
  import { barCount, windowBars, barsPath } from '../lib/waveform.js';
  import { time } from '../lib/format.js';

  let { path, height = 32, offset = 0 } = $props();
  let width = $state(0);
  const uid = $props.id();

  const wave = $derived(waveOf(path));
  const total = $derived(player.duration || wave?.data?.duration || 0);
  const levels = $derived(wave?.status === 'ready' && width > 0
    ? windowBars(wave.data.peak, wave.data.per_second, -offset, total - offset, barCount(width)) : []);
  const d = $derived(barsPath(levels, Math.max(width, 1), height, { minHeight: 2 }));
  const played = $derived(total > 0 ? Math.min(1, player.position / total) * width : 0);
</script>

<div class="seek" bind:clientWidth={width} style:height={`${height}px`}>
  {#if levels.length}
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <defs><clipPath id={`${uid}-p`}><rect x="0" y="0" width={played} height={height} /></clipPath></defs>
      <path class="rest" d={d} />
      <path class="played" d={d} clip-path={`url(#${uid}-p)`} />
      <rect class="head" x={Math.max(0, Math.min(width - 2, played - 1))} y="0" width="2" height={height} />
    </svg>
  {:else}
    <div class="line"><span style:width={`${total ? (player.position / total) * 100 : 0}%`}></span></div>
  {/if}
  <input type="range" min="0" max={Math.max(total, 1)} step="0.1" value={player.position}
    aria-label="Position" aria-valuetext={`${time(player.position)} of ${time(total)}`}
    oninput={(e) => seek(Number(e.currentTarget.value))} />
</div>

<style>
  .seek { position: relative; width: 100%; }
  svg { position: absolute; inset: 0; display: block; }
  .rest { fill: var(--ink-3); opacity: .45; }
  .played { fill: var(--accent); }
  .head { fill: var(--ink); }
  .line { position: absolute; left: 0; right: 0; top: 50%; height: 4px; margin-top: -2px; background: var(--line); border-radius: 2px; }
  .line span { display: block; height: 100%; background: var(--accent); border-radius: 2px; }
  input { position: absolute; inset: 0; width: 100%; height: 100%; margin: 0; opacity: 0; cursor: pointer; }
  .seek:focus-within { outline: 2px solid var(--accent); outline-offset: 3px; border-radius: 4px; }
</style>
