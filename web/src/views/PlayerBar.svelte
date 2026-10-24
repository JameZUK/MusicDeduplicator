<script>
  import { onMount } from 'svelte';
  import { player, register, toggle, switchTo, setAutoFlip, unload } from '../lib/player.svelte.js';
  import { time } from '../lib/format.js';
  import { route } from '../lib/router.svelte.js';
  import WaveSeek from './WaveSeek.svelte';

  let { oncompare } = $props();
  let audioA, audioB;
  onMount(() => register(audioA, audioB));

  // The full comparison has its own controls, so the bar stays out of the way there.
  const hidden = $derived(!player.loaded || route.query.a);

  function onkey(e) {
    if (!player.loaded || route.query.a || (e.target instanceof Element && e.target.closest('input, textarea, select, dialog'))) return;
    if (e.key === ' ') { toggle(); e.preventDefault(); }
    else if (e.key === '1') switchTo('a');
    else if (e.key === '2') switchTo('b');
  }
</script>

<svelte:window onkeydown={onkey} />

<audio bind:this={audioA} preload="auto"></audio>
<audio bind:this={audioB} preload="auto"></audio>

{#if !hidden}
  <div class="bar" role="region" aria-label="Player">
    <button class="btn primary play" onclick={toggle} aria-label={player.playing ? 'Pause' : 'Play'}>
      {#if player.playing}
        <svg viewBox="0 0 16 16"><rect x="3" y="2" width="3.5" height="12" rx="1" /><rect x="9.5" y="2" width="3.5" height="12" rx="1" /></svg>
      {:else}
        <svg viewBox="0 0 16 16"><path d="M4 2.5v11l9-5.5z" /></svg>
      {/if}
    </button>

    <div class="ab" role="radiogroup" aria-label="Which copy you hear">
      <button role="radio" aria-checked={player.active === 'a'} class:on={player.active === 'a'} onclick={() => switchTo('a')}>
        <b>A</b><span>{player.labelA}</span>
      </button>
      <button role="radio" aria-checked={player.active === 'b'} class:on={player.active === 'b'} onclick={() => switchTo('b')}>
        <b>B</b><span>{player.labelB}</span>
      </button>
    </div>

    <div class="seek">
      <WaveSeek path={player.active === 'a' ? player.a : player.b} height={30}
        offset={player.active === 'a' ? 0 : player.offset} />
      <span class="mono clock">{time(player.position)} / {time(player.duration)}</span>
    </div>

    <label class="flip" title="Switch between A and B automatically">
      <span class="eyebrow">auto A/B</span>
      <select value={player.autoFlip} onchange={(e) => setAutoFlip(Number(e.currentTarget.value))}>
        <option value={0}>off</option><option value={2}>2 s</option><option value={4}>4 s</option><option value={8}>8 s</option>
      </select>
    </label>

    <button class="btn" onclick={oncompare}>Full comparison</button>
    <button class="btn close" onclick={unload} aria-label="Close player">✕</button>
    {#if player.error}<span class="err">{player.error}</span>{/if}
  </div>
{/if}

<style>
  .bar {
    position: fixed; left: 16px; right: 16px; bottom: 16px; z-index: 20;
    display: grid; grid-template-columns: auto auto minmax(0, 1fr) auto auto auto; gap: 14px; align-items: center;
    padding: 10px 14px; border-radius: 14px;
    background: color-mix(in srgb, var(--panel) 92%, transparent); backdrop-filter: blur(12px);
    border: 1px solid var(--line); box-shadow: 0 20px 50px -20px rgba(0,0,0,.7);
    animation: rise .35s var(--ease) both;
  }
  .play { width: 42px; height: 42px; padding: 0; justify-content: center; border-radius: 50%; }
  .play svg { width: 15px; height: 15px; fill: currentColor; }
  .ab { display: flex; border: 1px solid var(--line); border-radius: 10px; overflow: hidden; max-width: 380px; }
  .ab button { all: unset; cursor: pointer; display: flex; align-items: center; gap: 8px; padding: 6px 12px; min-width: 0; max-width: 190px; color: var(--ink-3); }
  .ab button b { font-family: var(--font-display); font-size: 18px; }
  .ab button span { font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ab button.on { background: var(--accent); color: var(--accent-ink); }
  .ab button:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
  .seek { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px; align-items: center; min-width: 0; }
  .clock { font-size: 12px; color: var(--ink-2); }
  .flip { display: flex; flex-direction: column; gap: 2px; }
  select { background: var(--panel-2); color: var(--ink); border: 1px solid var(--line); border-radius: 6px; font: inherit; font-size: 12.5px; padding: 2px 4px; }
  .close { padding: 6px 10px; }
  .err { grid-column: 1 / -1; color: var(--remove); font-size: 12.5px; }
  @media (max-width: 900px) {
    .bar { grid-template-columns: auto minmax(0, 1fr) auto; }
    .seek { grid-column: 1 / -1; grid-row: 2; }
    .flip, .bar > .btn:not(.play):not(.close) { display: none; }
  }
</style>
