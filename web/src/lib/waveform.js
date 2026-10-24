// Waveform drawing maths. Adapted from Lyrion Anywhere (web/app/src/lib/analysis/waveform.ts)
// by the same author: peak buckets reduced to as many bars as fit, drawn as one SVG path.

export const BAR_PITCH = 3;
export const MIN_BARS = 16;
export const MAX_BARS = 1200;

/** How many bars fit a width (CSS px). */
export function barCount(widthPx, pitch = BAR_PITCH) {
  if (!Number.isFinite(widthPx) || widthPx <= 0 || !(pitch > 0)) return MIN_BARS;
  return Math.min(MAX_BARS, Math.max(MIN_BARS, Math.floor(widthPx / pitch)));
}

/** A bucket value (0-255) as a bar height (0-1); a gentle curve keeps quiet passages visible. */
export function level(v) {
  const x = Math.min(255, Math.max(0, Number.isFinite(v) ? v : 0)) / 255;
  return Math.pow(x, 0.7);
}

/**
 * Bar heights (0-1) for the time window [t0, t1) of a track whose peaks are sampled
 * `perSecond` times a second. Times outside the track give empty bars (null), so two
 * tracks with an offset line up on one timeline.
 */
export function windowBars(peaks, perSecond, t0, t1, count) {
  const out = new Array(count);
  const span = (t1 - t0) / count;
  for (let i = 0; i < count; i++) {
    const a = Math.floor((t0 + i * span) * perSecond);
    const b = Math.max(a + 1, Math.floor((t0 + (i + 1) * span) * perSecond));
    if (b <= 0 || a >= peaks.length) { out[i] = null; continue; }
    let m = 0;
    for (let k = Math.max(0, a); k < b && k < peaks.length; k++) m = Math.max(m, peaks[k]);
    out[i] = level(m);
  }
  return out;
}

const f = (x) => (Math.round(x * 100) / 100).toString();

/** An SVG path of bars centred on the middle line (or rising from the bottom with `anchor`). */
export function barsPath(levels, width, height, { gap = 1, minHeight = 1, anchor = 'middle' } = {}) {
  if (!levels.length || !(width > 0) || !(height > 0)) return '';
  const pitch = width / levels.length;
  const w = Math.max(pitch * 0.4, pitch - gap);
  let d = '';
  for (let i = 0; i < levels.length; i++) {
    const l = levels[i];
    if (l === null) continue;
    const h = Math.min(height, Math.max(minHeight, l * height));
    const y = anchor === 'bottom' ? height - h : anchor === 'top' ? 0 : (height - h) / 2;
    d += `M${f(i * pitch)} ${f(y)}h${f(w)}v${f(h)}h${f(-w)}z`;
  }
  return d;
}
