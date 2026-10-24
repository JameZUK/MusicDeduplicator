<script>
  // A format badge: hi-res / CD / lossy, coloured by tier.
  let { track = null, label = '' } = $props();

  const tier = $derived.by(() => {
    if (!track) return 'unknown';
    if (track.error) return 'broken';
    if (track.damaged) return 'damaged';
    if (track.lossless) return (track.bits || 16) > 16 || (track.sample_rate || 0) > 48000 ? 'hires' : 'cd';
    return track.bitrate ? 'lossy' : 'unknown';
  });
  const text = $derived.by(() => {
    if (label) return label;
    if (!track) return '—';
    if (track.error) return 'unreadable';
    if (track.damaged) return `${track.lossless ? `${track.bits || '?'}/${(track.sample_rate || 0) / 1000}` : `${Math.round((track.bitrate || 0) / 1000)}k`} ⚠`;
    if (track.lossless) return `${track.bits || '?'}/${(track.sample_rate || 0) / 1000}`;
    return track.bitrate ? `${Math.round(track.bitrate / 1000)}k` : '?';
  });
</script>

<span class={`q ${tier}`} title={track?.quality || ''}>{text}</span>

<style>
  .q {
    display: inline-block;
    font-family: var(--font-mono);
    font-size: 10.5px;
    line-height: 1;
    padding: 4px 6px 3px;
    border-radius: 4px;
    border: 1px solid currentColor;
    white-space: nowrap;
    letter-spacing: .02em;
  }
  .hires { color: var(--accent); background: var(--accent-soft); }
  .cd { color: var(--keep); background: var(--keep-soft); }
  .lossy { color: var(--ink-2); }
  .unknown { color: var(--ink-3); border-style: dashed; }
  .broken { color: var(--remove); background: var(--remove-soft); }
  .damaged { color: var(--accent); border-style: dashed; }
</style>
