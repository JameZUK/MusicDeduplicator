<script>
  // system -> dark -> light. Remembered per browser when storage is available.
  const order = ['system', 'dark', 'light'];
  let mode = $state(read());

  function read() {
    try { return localStorage.getItem('musicdedup-theme') || 'system'; } catch { return 'system'; }
  }

  $effect(() => {
    const root = document.documentElement;
    if (mode === 'system') root.removeAttribute('data-theme');
    else root.setAttribute('data-theme', mode);
    try { localStorage.setItem('musicdedup-theme', mode); } catch { /* private mode */ }
  });

  const next = () => (mode = order[(order.indexOf(mode) + 1) % order.length]);
</script>

<button class="btn toggle" onclick={next} title={`Theme: ${mode}`} aria-label={`Theme: ${mode}. Change theme`}>
  {#if mode === 'dark'}
    <svg viewBox="0 0 24 24"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5Z" /></svg>
  {:else if mode === 'light'}
    <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="4.5" /><path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M4.9 19.1l1.8-1.8M17.3 6.7l1.8-1.8" /></svg>
  {:else}
    <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5" /><path d="M12 3.5v17a8.5 8.5 0 0 0 0-17Z" class="fill" /></svg>
  {/if}
</button>

<style>
  .toggle { padding: 7px; border-radius: 50%; }
  svg { width: 17px; height: 17px; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; }
  .fill { fill: currentColor; stroke: none; }
</style>
