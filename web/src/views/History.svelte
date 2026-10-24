<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import { store } from '../lib/store.svelte.js';
  import { waitForJob, describeCounts } from '../lib/jobs.js';
  import { bytes, when } from '../lib/format.js';

  let entries = $state([]);
  let busy = $state(null);
  let message = $state('');

  const load = async () => (entries = await api.history());
  onMount(load);

  // A move can be undone once; deletes can't be undone at all.
  const undone = $derived(new Set(entries.filter((e) => e.op === 'undo').map((e) => e.journal)));

  async function undo(entry) {
    busy = entry.journal;
    message = '';
    try {
      const { job } = await api.undo(entry.journal);
      const done = await waitForJob(job);
      message = done.state === 'done' ? `Restored: ${describeCounts(done.counts)}.` : `Undo failed: ${done.error}`;
    } catch (e) {
      store.error = e.message;
    } finally {
      busy = null;
      await load();
    }
  }
</script>

<section class="history rise">
  <header>
    <span class="eyebrow">from this machine's history, CLI and dashboard alike</span>
    <h1>History</h1>
  </header>
  {#if message}<p class="msg panel">{message}</p>{/if}

  <ol class="timeline">
    {#each entries as e}
      <li class:undo={e.op === 'undo'}>
        <span class="when mono">{when(e.time)}</span>
        <span class="mark" aria-hidden="true"></span>
        <div class="what panel">
          <div class="line">
            <strong>{e.op === 'undo' ? 'Undo' : e.mode === 'delete' ? 'Deleted' : 'Moved to quarantine'}</strong>
            <span class="mono dim">{describeCounts(e.counts)}{e.bytes ? ` · ${bytes(e.bytes)}` : ''}</span>
            {#if e.skipped}<span class="warn mono">{e.skipped} skipped</span>{/if}
          </div>
          <div class="line dim small">
            <span>{e.user || 'unknown user'}</span>
            {#if e.journal}<span class="mono path" title={e.journal}>{e.journal}</span>{/if}
          </div>
          {#if e.op === 'apply' && e.mode === 'move'}
            <div class="line">
              {#if undone.has(e.journal)}
                <span class="dim small">Undone</span>
              {:else}
                <button class="btn" disabled={busy !== null} onclick={() => undo(e)}>
                  {busy === e.journal ? 'Restoring…' : 'Undo this'}
                </button>
              {/if}
            </div>
          {/if}
        </div>
      </li>
    {:else}
      <li class="empty">Nothing has been applied yet.</li>
    {/each}
  </ol>
</section>

<style>
  header { margin-bottom: 20px; }
  h1 { font-size: 40px; font-weight: 520; margin-top: 4px; }
  .msg { padding: 10px 14px; }
  .timeline { list-style: none; margin: 0; padding: 0; position: relative; }
  .timeline::before { content: ''; position: absolute; left: 186px; top: 6px; bottom: 6px; width: 1px; background: var(--line); }
  li { display: grid; grid-template-columns: 170px 32px minmax(0, 1fr); align-items: start; margin-bottom: 14px; }
  .when { font-size: 12px; color: var(--ink-3); padding-top: 14px; text-align: right; padding-right: 8px; }
  .mark { width: 11px; height: 11px; border-radius: 50%; background: var(--accent); margin: 16px auto 0; box-shadow: 0 0 0 4px var(--bg); position: relative; }
  li.undo .mark { background: var(--keep); }
  .what { padding: 12px 14px; display: flex; flex-direction: column; gap: 6px; min-width: 0; }
  .line { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; min-width: 0; }
  .dim { color: var(--ink-3); }
  .small { font-size: 12.5px; }
  .warn { color: var(--accent); font-size: 12px; }
  .path { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; flex: 1; }
  .empty { display: block; color: var(--ink-3); padding-left: 210px; }
  @media (max-width: 700px) {
    .timeline::before { left: 8px; }
    li { grid-template-columns: 18px minmax(0, 1fr); }
    .when { grid-column: 2; text-align: left; padding: 0; order: -1; }
    .mark { grid-row: 1 / span 2; margin: 4px 0 0; }
    .empty { padding-left: 0; }
  }
</style>
