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
    /* A record: grooves, and a centre label carrying the initials. Same in both themes. */
    background:
      radial-gradient(circle at 50% 50%, hsl(var(--h) 45% 32%) 0 30%, hsl(var(--h) 25% 12%) 31% 33%, transparent 34%),
      repeating-radial-gradient(circle at 50% 50%, hsl(var(--h) 20% 14%) 0 2px, hsl(var(--h) 20% 19%) 2px 4px);
  }
  .label span { font-family: var(--font-display); color: hsl(var(--h) 70% 88%); font-size: 1.05em; letter-spacing: .02em; }
</style>
