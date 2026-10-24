<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import { store } from '../lib/store.svelte.js';
  import { waitForJob, describeCounts } from '../lib/jobs.js';
  import { bytes, rel } from '../lib/format.js';

  let { onclose } = $props();

  let preview = $state(null);
  let error = $state('');
  let mode = $state(store.session.move_to ? 'move' : 'delete');
  let confirmText = $state('');
  let job = $state(null);
  let ranForReal = $state(false);
  let dialog;

  const decisions = $state.snapshot(store.decisions);
  const canMove = !!store.session.move_to;
  const canDelete = store.session.allow_delete;
  const ready = $derived(preview && preview.summary.files_to_remove > 0 && (mode === 'move' ? canMove : canDelete && confirmText === 'delete'));

  onMount(async () => {
    dialog.showModal();
    try { preview = await api.preview(decisions); } catch (e) { error = e.message; }
  });

  async function run(dryRun) {
    error = '';
    try {
      const started = await api.apply({ decisions, mode, dry_run: dryRun, confirm: mode === 'delete' ? confirmText : undefined });
      job = { state: 'running', dryRun };
      job = { ...(await waitForJob(started.job)), dryRun };
      if (!dryRun && job.state === 'done') ranForReal = true;
    } catch (e) {
      error = e.message;
      job = null;
    }
  }

  function close() {
    dialog.close();
    onclose(ranForReal);
  }

  const byFolder = $derived.by(() => {
    if (!preview) return [];
    const m = new Map();
    for (const r of preview.removals) {
      const d = r.path.slice(0, r.path.lastIndexOf('/'));
      const e = m.get(d) || { folder: d, files: 0, size: 0 };
      e.files++; e.size += r.size;
      m.set(d, e);
    }
    return [...m.values()];
  });
</script>

<dialog bind:this={dialog} oncancel={(e) => { e.preventDefault(); close(); }} aria-labelledby="apply-title">
  <header>
    <span class="eyebrow">nothing happens until you press the button</span>
    <h2 id="apply-title">Apply your decisions</h2>
  </header>

  {#if error}<p class="err" role="alert">{error}</p>{/if}

  {#if !preview && !error}
    <p class="dim">Working out exactly what would change…</p>
  {:else if preview}
    <div class="numbers">
      <div><span class="big mono">{preview.summary.files_to_remove}</span><span class="eyebrow">files</span></div>
      <div><span class="big mono">{byFolder.length}</span><span class="eyebrow">folders</span></div>
      <div><span class="big mono">{bytes(preview.summary.bytes_to_free)}</span><span class="eyebrow">freed</span></div>
    </div>

    {#if preview.warnings.length}
      <div class="warnings">
        <strong>Check these first</strong>
        <ul>{#each preview.warnings as w}<li>{w}</li>{/each}</ul>
      </div>
    {/if}

    <details>
      <summary>Folders affected</summary>
      <ul class="folders">
        {#each byFolder as f}
          <li><span class="clip">{rel(f.folder, store.plan.roots)}</span><span class="mono dim">{f.files} · {bytes(f.size)}</span></li>
        {/each}
      </ul>
    </details>

    <fieldset>
      <legend class="eyebrow">how</legend>
      <label class:disabled={!canMove}>
        <input type="radio" bind:group={mode} value="move" disabled={!canMove} />
        <span><strong>Move to quarantine</strong> <span class="dim">— reversible from History</span><br />
          <span class="mono dim small">{store.session.move_to || 'not configured (start the server with --move-to)'}</span></span>
      </label>
      <label class:disabled={!canDelete}>
        <input type="radio" bind:group={mode} value="delete" disabled={!canDelete} />
        <span><strong>Delete permanently</strong> <span class="dim">— cannot be undone</span>
          {#if !canDelete}<br /><span class="mono dim small">disabled (start the server with --allow-delete)</span>{/if}</span>
      </label>
      {#if mode === 'delete'}
        <input class="confirm" placeholder="Type delete to confirm" bind:value={confirmText} autocomplete="off" />
      {/if}
    </fieldset>
  {/if}

  {#if job}
    <div class="result" class:failed={job.state === 'failed'}>
      {#if job.state === 'running'}
        <span class="dim">{job.dryRun ? 'Checking every file…' : 'Working…'}</span>
      {:else if job.state === 'failed'}
        <strong>Failed:</strong> {job.error}
      {:else}
        <strong>{job.dryRun ? 'Dry run:' : 'Done:'}</strong> {describeCounts(job.counts)} · {bytes(job.bytes)} {job.dryRun ? 'would be freed' : 'freed'}.
        {#if job.skipped?.length}
          <details><summary>{job.skipped.length} skipped (changed since the scan, or a kept copy is missing)</summary>
            <ul class="folders">{#each job.skipped as s}<li><span class="clip">{rel(s.path, store.plan.roots)}</span><span class="dim small">{s.reason}</span></li>{/each}</ul>
          </details>
        {/if}
      {/if}
    </div>
  {/if}

  <footer>
    <button class="btn" onclick={close}>{ranForReal ? 'Close' : 'Cancel'}</button>
    {#if !ranForReal}
      <button class="btn" disabled={!ready || job?.state === 'running'} onclick={() => run(true)}>Dry run</button>
      <button class={`btn ${mode === 'delete' ? 'danger' : 'primary'}`} disabled={!ready || job?.state === 'running'} onclick={() => run(false)}>
        {mode === 'delete' ? 'Delete files' : 'Move files'}
      </button>
    {/if}
  </footer>
</dialog>

<style>
  dialog {
    width: min(640px, calc(100vw - 32px)); max-height: calc(100vh - 48px); overflow: auto;
    background: var(--panel); color: var(--ink); border: 1px solid var(--line); border-radius: 14px;
    padding: 24px 26px; box-shadow: 0 40px 80px -30px rgba(0,0,0,.7);
  }
  dialog::backdrop { background: rgba(10, 8, 5, .55); backdrop-filter: blur(3px); }
  h2 { font-size: 28px; margin: 4px 0 16px; }
  .numbers { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 16px; }
  .numbers div { display: flex; flex-direction: column; padding: 12px; border: 1px solid var(--line-soft); border-radius: 8px; }
  .big { font-size: 24px; color: var(--accent); }
  .warnings { border: 1px solid var(--accent); background: var(--accent-soft); border-radius: 8px; padding: 10px 14px; margin-bottom: 14px; font-size: 13.5px; }
  .warnings ul { margin: 6px 0 0; padding-left: 18px; }
  details { margin-bottom: 14px; font-size: 13.5px; }
  summary { cursor: pointer; color: var(--ink-2); }
  .folders { list-style: none; padding: 0; margin: 8px 0 0; max-height: 200px; overflow: auto; }
  .folders li { display: flex; gap: 10px; padding: 4px 0; border-bottom: 1px solid var(--line-soft); }
  .clip { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  fieldset { border: 1px solid var(--line-soft); border-radius: 8px; padding: 10px 14px 14px; margin: 0 0 14px; display: flex; flex-direction: column; gap: 10px; }
  label { display: flex; gap: 10px; align-items: flex-start; cursor: pointer; }
  label.disabled { opacity: .5; cursor: not-allowed; }
  input[type='radio'] { accent-color: var(--accent); margin-top: 4px; }
  .confirm { padding: 8px 11px; border-radius: 6px; border: 1px solid var(--remove); background: var(--panel-2); color: var(--ink); font: inherit; }
  .dim { color: var(--ink-3); }
  .small { font-size: 12px; }
  .err { color: var(--remove); }
  .result { border-radius: 8px; padding: 10px 14px; background: var(--keep-soft); margin-bottom: 14px; font-size: 14px; }
  .result.failed { background: var(--remove-soft); }
  footer { display: flex; justify-content: flex-end; gap: 10px; }
</style>
