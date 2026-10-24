<script>
  // Album artwork, with a generated "record label" when there isn't any.
  import { coverUrl } from '../lib/api.js';
  let { folder, size = 96, title = '' } = $props();
  let failed = $state(false);

  const hue = $derived([...folder].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7));
  const initials = $derived(title.replace(/[^\p{L}\p{N} ]/gu, '').split(/\s+/).filter(Boolean).slice(0, 2)
    .map((w) => w[0]).join('').toUpperCase());
</script>

<div class="cover" style:width={`${size}px`} style:height={`${size}px`}>
  {#if !failed}
    <img src={coverUrl(folder)} alt="" loading="lazy" onerror={() => (failed = true)} />
  {:else}
    <div class="label" style:--h={hue}>
      <span>{initials || '♪'}</span>
    </div>
  {/if}
</div>

<style>
  .cover { flex: none; border-radius: 6px; overflow: hidden; background: var(--panel-2); box-shadow: 0 6px 18px -10px rgba(0,0,0,.7); }
  img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .label {
    width: 100%; height: 100%; display: grid; place-items: center;
    background:
      radial-gradient(circle at 50% 50%, var(--panel) 0 14%, transparent 15%),
      repeating-radial-gradient(circle at 50% 50%, hsl(var(--h) 25% 18%) 0 2px, hsl(var(--h) 25% 22%) 2px 4px);
  }
  .label span { font-family: var(--font-display); color: hsl(var(--h) 60% 75%); font-size: 1.1em; mix-blend-mode: screen; }
</style>
