<script>
  import { store } from '../lib/store.svelte.js';
  import { startScan, stopScan, eta } from '../lib/scan.svelte.js';

  let { big = false } = $props();
  let busy = $state(false);

  const s = $derived(store.scan);
  const running = $derived(s.state === 'running');
  const pct = $derived(s.total ? Math.min(100, (s.done / s.total) * 100) : 0);
  const e = $derived(eta(s));
  const stageText = $derived({
    starting: 'Starting', walking: 'Finding music', fingerprinting: 'Fingerprinting',
    comparing: 'Comparing tracks',
  }[s.stage] || 'Scanning');

  function fmt(sec) {
    if (!Number.isFinite(sec)) return '';
    const m = Math.round(sec / 60);
    return m >= 60 ? `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m` : `${m}m`;
  }

  async function act(fn) {
    busy = true;
    try { await fn(); } catch (err) { store.error = err.message; } finally { busy = false; }
  }
</script>

{#if store.session?.can_scan}
  {#if running}
    <div class="scan" class:big role="status" aria-live="polite">
      <div class="line">
        <span class="dot" aria-hidden="true"></span>
        <strong>{stageText}</strong>
        {#if s.stage === 'walking'}
          <span class="mono">{s.done.toLocaleString()} files found</span>
        {:else if s.total}
          <span class="mono">{s.done.toLocaleString()} / {s.total.toLocaleString()}</span>
        {/if}
        {#if e}<span class="mono dim">{e.rate.toFixed(1)}/s · {fmt(e.left)} left</span>{/if}
        <button class="btn stop" disabled={busy} onclick={() => act(stopScan)}>Stop scan</button>
      </div>
      <div class="bar"><span class:indeterminate={!s.total} style:width={s.total ? `${pct}%` : '100%'}></span></div>
      {#if big}<p class="dim">Fingerprints are saved as they are made, so stopping loses nothing; the next scan carries on from there.</p>{/if}
    </div>
  {:else}
    <button class="btn rescan" class:primary={big} disabled={busy} onclick={() => act(startScan)}
      title={`Rescan ${store.session.library.join(', ')}`}>
      {big ? 'Start the scan' : 'Rescan'}
    </button>
    {#if s.state === 'failed'}<span class="err">Last scan failed: {s.error}</span>{/if}
    {#if s.state === 'cancelled' && big}<span class="dim">The last scan was stopped. Start again to carry on.</span>{/if}
  {/if}
{/if}

<style>
  .scan { display: flex; flex-direction: column; gap: 5px; min-width: 300px; }
  .scan.big { min-width: 0; width: min(560px, 100%); }
  .line { display: flex; align-items: center; gap: 10px; font-size: 13px; flex-wrap: wrap; }
  .line .mono { font-size: 12px; }
  .dim { color: var(--ink-3); font-size: 12px; margin: 0; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 0 0 var(--accent); animation: ping 1.6s infinite; }
  @keyframes ping { 70% { box-shadow: 0 0 0 7px transparent; } }
  .stop { margin-left: auto; padding: 2px 10px; font-size: 12px; border-color: var(--remove); color: var(--remove); }
  .bar { height: 4px; border-radius: 2px; background: var(--line-soft); overflow: hidden; }
  .bar span { display: block; height: 100%; background: var(--accent); transition: width .6s var(--ease); }
  .bar span.indeterminate { width: 30% !important; animation: slide 1.4s infinite ease-in-out; }
  @keyframes slide { from { transform: translateX(-100%); } to { transform: translateX(340%); } }
  .rescan { font-size: 13px; }
  .err { color: var(--remove); font-size: 12px; }
</style>
