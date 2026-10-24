<script>
  import { onMount } from 'svelte';
  import { api, loadSession } from './lib/api.js';
  import { store, decidedBytes, decisionKind } from './lib/store.svelte.js';
  import { route, go } from './lib/router.svelte.js';
  import { bytes } from './lib/format.js';
  import Overview from './views/Overview.svelte';
  import Review from './views/Review.svelte';
  import Compare from './views/Compare.svelte';
  import PlayerBar from './views/PlayerBar.svelte';
  import { player } from './lib/player.svelte.js';
  import { openCompare, closeCompare } from './lib/router.svelte.js';
  import History from './views/History.svelte';
  import ApplyDialog from './views/ApplyDialog.svelte';
  import ThemeToggle from './views/ThemeToggle.svelte';
  import Library from './views/Library.svelte';
  import ScanControl from './views/ScanControl.svelte';
  import { watchScans } from './lib/scan.svelte.js';

  let loading = $state(true);
  let applying = $state(false);

  const decided = $derived(store.plan ? store.plan.groups.filter((g) => decisionKind(g) !== 'undecided').length : 0);
  const actionable = $derived(
    store.plan ? store.plan.groups.filter((g) => ['accept', 'changed'].includes(decisionKind(g))).length : 0,
  );
  const withinCount = $derived(store.decisions.within.length);

  async function refresh() {
    const session = await loadSession();
    store.session = session;
    if (!session.has_plan) { store.plan = null; return; }
    const [plan, decisions] = await Promise.all([api.plan(), api.decisions()]);
    store.plan = plan;
    store.decisions = { groups: decisions.groups || {}, within: decisions.within || [] };
  }

  onMount(async () => {
    try {
      await refresh();
    } catch (e) {
      store.error = e.message;
    } finally {
      loading = false;
    }
    // When a scan finishes, load the new plan (decisions carry over on the server).
    watchScans(async (s) => {
      if (s.state === 'done') {
        try { await refresh(); } catch (e) { store.error = e.message; }
      }
    });
  });

  const nav = [
    ['overview', 'Overview'],
    ['review', 'Review'],
    ['library', 'Library'],
    ['history', 'History'],
  ];
</script>

<div class="shell">
  <header class="top">
    <a class="brand" href="#/overview" aria-label="musicdedup overview">
      <svg viewBox="0 0 32 32" aria-hidden="true">
        <circle cx="12" cy="16" r="7" />
        <circle cx="20" cy="16" r="7" class="second" />
      </svg>
      <span>music<em>dedup</em></span>
    </a>
    <nav>
      {#each nav as [view, label]}
        <a href={`#/${view}`} class:active={route.view === view}>{label}</a>
      {/each}
    </nav>
    <div class="right">
      {#if store.plan || store.scan.state === 'running'}<ScanControl />{/if}
      {#if store.plan}
        <div class="tally" title="Groups you've decided on">
          <span class="eyebrow">decided</span>
          <span class="mono">{decided}/{store.plan.groups.length}</span>
          {#if store.saving}<span class="dot" aria-label="saving"></span>{/if}
        </div>
        <button class="btn primary" disabled={!actionable && !withinCount} onclick={() => (applying = true)}>
          Apply
          <span class="mono">{actionable + withinCount}</span>
          <span class="sub mono">{bytes(decidedBytes(store.plan))}</span>
        </button>
      {/if}
      <ThemeToggle />
    </div>
  </header>

  {#if store.error}
    <div class="error" role="alert">
      <span>{store.error}</span>
      <button class="btn" onclick={() => (store.error = '')}>Dismiss</button>
    </div>
  {/if}

  <main>
    {#if loading}
      <div class="loading"><span class="eyebrow">loading the plan…</span></div>
    {:else if !store.plan && store.session}
      <section class="first rise">
        <span class="eyebrow">no plan yet</span>
        <h1>{store.scan.state === 'running' ? 'Scanning your music…' : 'Scan your music to begin'}</h1>
        <p>{store.session.can_scan
          ? `The first scan fingerprints every track in ${store.session.library.join(', ')}. That takes a while, but later scans only look at what has changed.`
          : 'Run musicdedup scan, or start the dashboard with --library so it can scan for you.'}</p>
        <ScanControl big />
      </section>
    {:else if store.plan}
      {#if route.view === 'review'}
        <Review id={route.id} />
      {:else if route.view === 'library'}
        <Library />
      {:else if route.view === 'history'}
        <History />
      {:else}
        <Overview />
      {/if}
    {/if}
  </main>

  <footer>
    {#if store.session}
      <span class="mono">v{store.session.version}</span>
      <span>·</span>
      <span>{store.session.user ? `signed in as ${store.session.user}` : 'LAN access, no login'}</span>
      <span>·</span>
      <span class="mono path" title={store.session.plan_path}>{store.session.plan_path.split('/').pop()}</span>
    {/if}
  </footer>
</div>

{#if store.plan && route.query.a && route.query.b}
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
  <div class="sheet-backdrop" onclick={closeCompare}></div>
  <div class="sheet" role="dialog" aria-modal="true" aria-label="Track comparison">
    {#key `${route.query.a}|${route.query.b}`}
      <Compare a={route.query.a} b={route.query.b} onclose={closeCompare} />
    {/key}
  </div>
{/if}

<PlayerBar oncompare={() => openCompare(player.a, player.b)} />

{#if applying}
  <ApplyDialog onclose={async (changed) => { applying = false; if (changed) { await refresh(); go('history'); } }} />
{/if}

<style>
  .sheet-backdrop { position: fixed; inset: 0; z-index: 30; background: rgba(10, 8, 5, .5); backdrop-filter: blur(2px); animation: fade .2s both; }
  .sheet {
    /* Centred with margins, not a transform: the entry animation uses transform. */
    position: fixed; z-index: 31; left: 0; right: 0; top: 4vh; margin: 0 auto;
    width: min(1280px, calc(100vw - 32px)); max-height: 92vh; overflow: auto;
    background: var(--bg); border: 1px solid var(--line); border-radius: 16px; padding: 22px 24px;
    box-shadow: 0 40px 100px -30px rgba(0,0,0,.8); animation: rise .3s var(--ease) both;
  }
  @keyframes fade { from { opacity: 0; } }
  .shell { min-height: 100vh; display: grid; grid-template-rows: auto auto 1fr auto; }

  .top {
    position: sticky; top: 0; z-index: 10;
    display: flex; align-items: center; gap: 28px;
    padding: 12px 28px;
    background: color-mix(in srgb, var(--bg) 82%, transparent);
    backdrop-filter: blur(10px);
    border-bottom: 1px solid var(--line-soft);
  }

  .brand { display: flex; align-items: center; gap: 10px; text-decoration: none; }
  .brand svg { width: 30px; height: 30px; fill: none; stroke: var(--accent); stroke-width: 2.4; }
  .brand .second { opacity: .5; }
  .brand span { font-family: var(--font-display); font-size: 21px; font-weight: 600; letter-spacing: -.02em; }
  .brand em { font-style: italic; color: var(--accent); font-weight: 450; }

  nav { display: flex; gap: 4px; }
  nav a {
    text-decoration: none; padding: 6px 12px; border-radius: 999px; color: var(--ink-2);
    font-size: 14px; transition: color .15s, background .15s;
  }
  nav a:hover { color: var(--ink); }
  nav a.active { color: var(--ink); background: var(--panel-2); box-shadow: inset 0 0 0 1px var(--line); }

  .right { margin-left: auto; display: flex; align-items: center; gap: 14px; }
  .tally { display: flex; align-items: baseline; gap: 8px; }
  .tally .mono { font-size: 14px; }
  .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); animation: pulse 1s infinite; align-self: center; }
  @keyframes pulse { 50% { opacity: .2; } }
  .sub { opacity: .7; font-weight: 400; font-size: 12px; }

  .error {
    margin: 12px 28px 0; padding: 10px 14px; border-radius: var(--radius-sm);
    background: var(--remove-soft); border: 1px solid var(--remove); color: var(--ink);
    display: flex; justify-content: space-between; align-items: center; gap: 12px;
  }

  main { padding: 26px 28px 110px; min-width: 0; }
  .loading { display: grid; place-items: center; height: 50vh; }
  .first { max-width: 680px; margin: 10vh auto; display: flex; flex-direction: column; gap: 14px; }
  .first h1 { font-size: clamp(32px, 4.5vw, 54px); font-weight: 500; }
  .first p { color: var(--ink-2); font-size: 16px; margin: 0; }

  footer {
    display: flex; gap: 8px; padding: 14px 28px; color: var(--ink-3); font-size: 12px;
    border-top: 1px solid var(--line-soft); flex-wrap: wrap;
  }
  .path { overflow: hidden; text-overflow: ellipsis; }

  @media (max-width: 760px) {
    .top { flex-wrap: wrap; gap: 12px; padding: 10px 16px; position: static; }
    .right { margin-left: 0; width: 100%; justify-content: space-between; }
    main { padding: 18px 16px 32px; }
    .error { margin: 12px 16px 0; }
    footer { padding: 12px 16px; }
  }
</style>
