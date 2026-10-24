// One player for the whole app, built on the Web Audio API.
//
// Both copies are downloaded and decoded into memory, then played from one audio
// clock through their own gain nodes. Switching A/B is a 10 ms crossfade between
// the gains, so it is instant, sample-accurate and never loses its place. Seeking
// restarts both sources from memory, so nothing waits on the network once loaded.
// (Two streaming <audio> elements can't do this reliably: they drift, and
// re-syncing them means network seeks that stall, especially in Firefox.)
//
// Positions are in A's time; B's time = A's time - offset.

const MAX_FILE_BYTES = 400 * 1024 * 1024;   // decoded size is several times this
const FADE = 0.01;

export const player = $state({
  loaded: false,
  status: 'idle',        // idle | loading | ready | error
  progress: 0,           // 0-1 while loading both files
  a: null, b: null,
  labelA: '', labelB: '',
  offset: 0,
  active: 'a',
  playing: false,
  position: 0,
  duration: 0,
  autoFlip: 0,
  error: '',
});

let ctx = null;
let buffers = { a: null, b: null };
let gains = { a: null, b: null };
let sources = [];
let startedAt = 0;       // ctx time when playback (re)started
let startPos = 0;        // A-time at that moment
let loadToken = 0;
let abort = null;
let raf = 0;
let flipTimer = null;
let wantPlay = false;

function audioContext() {
  if (!ctx) {
    ctx = new (window.AudioContext || window.webkitAudioContext)();
    for (const k of ['a', 'b']) {
      gains[k] = ctx.createGain();
      gains[k].connect(ctx.destination);
    }
    applyGains(true);
  }
  return ctx;
}

function applyGains(immediate = false) {
  if (!ctx) return;
  const t = ctx.currentTime;
  for (const k of ['a', 'b']) {
    const g = gains[k].gain;
    const target = player.active === k ? 1 : 0;
    g.cancelScheduledValues(t);
    if (immediate) g.setValueAtTime(target, t);
    else { g.setValueAtTime(g.value, t); g.linearRampToValueAtTime(target, t + FADE); }
  }
}

async function fetchBytes(path, signal, onProgress) {
  const res = await fetch(`./api/audio?path=${encodeURIComponent(path)}`, { signal, credentials: 'same-origin' });
  if (!res.ok) throw new Error(`could not load audio (${res.status})`);
  const total = Number(res.headers.get('Content-Length')) || 0;
  if (total > MAX_FILE_BYTES) throw new Error('this file is too long to compare in the browser');
  const reader = res.body.getReader();
  const chunks = [];
  let got = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    got += value.length;
    if (total) onProgress(got / total);
  }
  const out = new Uint8Array(got);
  let at = 0;
  for (const c of chunks) { out.set(c, at); at += c.length; }
  return out.buffer;
}

/** Loads a pair (downloads and decodes both). Call play() to start. */
export async function load(a, b, { labelA = 'A', labelB = 'B', offset = 0 } = {}) {
  if (player.a === a && player.b === b && player.status !== 'error') {
    Object.assign(player, { labelA, labelB, offset });
    player.loaded = true;
    return;
  }
  stopSources();
  abort?.abort();
  abort = new AbortController();
  const token = ++loadToken;
  buffers = { a: null, b: null };
  Object.assign(player, { loaded: true, status: 'loading', progress: 0, a, b, labelA, labelB, offset,
    active: 'a', playing: false, position: 0, duration: 0, error: '' });
  applyGains(true);
  const parts = { a: 0, b: 0 };
  const update = () => { if (token === loadToken) player.progress = (parts.a + parts.b) / 2 * 0.85; };
  try {
    const c = audioContext();
    const [bytesA, bytesB] = await Promise.all([
      fetchBytes(a, abort.signal, (p) => { parts.a = p; update(); }),
      fetchBytes(b, abort.signal, (p) => { parts.b = p; update(); }),
    ]);
    if (token !== loadToken) return;
    player.progress = 0.9;
    const [bufA, bufB] = await Promise.all([c.decodeAudioData(bytesA), c.decodeAudioData(bytesB)]);
    if (token !== loadToken) return;
    buffers = { a: bufA, b: bufB };
    Object.assign(player, { status: 'ready', progress: 1, duration: bufA.duration });
    if (wantPlay) { wantPlay = false; play(); }
  } catch (e) {
    if (token !== loadToken || e.name === 'AbortError') return;
    Object.assign(player, { status: 'error', error: `Can't play these files: ${e.message}` });
  }
}

export function setOffset(offset) {
  player.offset = offset || 0;
  if (player.playing) restart(currentPosition());
}

function currentPosition() {
  if (!player.playing || !ctx) return player.position;
  return Math.max(startPos, startPos + (ctx.currentTime - startedAt));
}

function stopSources() {
  for (const s of sources) {
    s.onended = null;
    try { s.stop(); } catch { /* already stopped */ }
    s.disconnect();
  }
  sources = [];
  cancelAnimationFrame(raf);
}

function restart(pos) {
  stopSources();
  const c = audioContext();
  const when = c.currentTime + 0.03;
  for (const k of ['a', 'b']) {
    const buf = buffers[k];
    const local = k === 'a' ? pos : pos - player.offset;
    if (!buf || local >= buf.duration) continue;
    const src = c.createBufferSource();
    src.buffer = buf;
    src.connect(gains[k]);
    // A negative local time means this copy starts a little later on the timeline.
    if (local < 0) src.start(when - local, 0);
    else src.start(when, local);
    sources.push(src);
  }
  startedAt = when;
  startPos = pos;
  player.position = pos;
  const tick = () => {
    player.position = currentPosition();
    if (player.position >= player.duration) { pause(); player.position = player.duration; return; }
    raf = requestAnimationFrame(tick);
  };
  raf = requestAnimationFrame(tick);
}

export async function play() {
  if (!player.loaded) return;
  if (player.status === 'loading') { wantPlay = true; return; }
  if (player.status !== 'ready') return;
  const c = audioContext();
  if (c.state === 'suspended') await c.resume();
  const pos = player.position >= player.duration ? 0 : player.position;
  applyGains(true);
  restart(pos);
  player.playing = true;
  scheduleFlip();
}

export function pause() {
  wantPlay = false;
  if (player.playing) player.position = currentPosition();
  stopSources();
  player.playing = false;
  clearInterval(flipTimer);
}

export const toggle = () => (player.playing || wantPlay ? pause() : play());

export function switchTo(which) {
  if (which === player.active) return;
  player.active = which;
  applyGains();
}

export const flip = () => switchTo(player.active === 'a' ? 'b' : 'a');

/** Seek; `which` also makes that copy the audible one. */
export function seek(aTime, which = null) {
  const pos = Math.max(0, Math.min(aTime, player.duration || aTime));
  if (which) switchTo(which);
  if (player.playing) restart(pos);
  else player.position = pos;
}

export function setAutoFlip(seconds) {
  player.autoFlip = seconds;
  scheduleFlip();
}

function scheduleFlip() {
  clearInterval(flipTimer);
  if (player.autoFlip > 0 && player.playing) flipTimer = setInterval(flip, player.autoFlip * 1000);
}

export function unload() {
  pause();
  abort?.abort();
  loadToken++;
  buffers = { a: null, b: null };
  Object.assign(player, { loaded: false, status: 'idle', a: null, b: null, position: 0, duration: 0, progress: 0 });
}
