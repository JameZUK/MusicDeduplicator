// One player for the whole app: two <audio> elements (A and B) that play together,
// with only the selected one audible. Switching just swaps which is muted, so it is
// instant and keeps your place. The inaudible one is nudged back into sync when it
// drifts. Positions are always in A's time; B's time = A's time - offset.

export const player = $state({
  loaded: false,
  a: null, b: null,
  labelA: '', labelB: '',
  offset: 0,
  active: 'a',
  playing: false,
  position: 0,
  duration: 0,
  autoFlip: 0,   // seconds between automatic switches; 0 = off
  error: '',
});

let elA = null;
let elB = null;
let syncTimer = null;
let flipTimer = null;

export function register(a, b) {
  elA = a;
  elB = b;
  for (const el of [a, b]) {
    el.addEventListener('ended', () => { if (el === audible()) pause(); });
    el.addEventListener('error', () => {
      if (el.getAttribute('src')) player.error = 'This browser could not play one of the files.';
    });
  }
  a.addEventListener('loadedmetadata', () => (player.duration = a.duration || 0));
}

const audible = () => (player.active === 'a' ? elA : elB);
const silent = () => (player.active === 'a' ? elB : elA);
const timeFor = (el, aTime) => Math.max(0, el === elA ? aTime : aTime - player.offset);
const aTimeOf = (el) => (el === elA ? el.currentTime : el.currentTime + player.offset);

function applyMute() {
  if (!elA) return;
  elA.muted = player.active !== 'a';
  elB.muted = player.active !== 'b';
}

/** Loads a pair. Keeps playing state off; call play() to start. */
export function load(a, b, { labelA = 'A', labelB = 'B', offset = 0 } = {}) {
  if (!elA) return;
  const same = player.a === a && player.b === b;
  if (!same) {
    pause();
    Object.assign(player, { a, b, labelA, labelB, offset, active: 'a', position: 0, duration: 0, error: '' });
    elA.src = `./api/audio?path=${encodeURIComponent(a)}`;
    elB.src = `./api/audio?path=${encodeURIComponent(b)}`;
    applyMute();
  } else {
    Object.assign(player, { labelA, labelB, offset });
  }
  player.loaded = true;
}

export function setOffset(offset) {
  player.offset = offset || 0;
  if (player.playing) resync(true);
}

export async function play() {
  if (!elA || !player.loaded) return;
  applyMute();
  const t = player.position;
  elA.currentTime = timeFor(elA, t);
  elB.currentTime = timeFor(elB, t);
  try {
    await Promise.all([elA.play(), elB.play()]);
    player.playing = true;
    player.error = '';
  } catch (e) {
    player.error = `Playback failed: ${e.message}`;
    pause();
    return;
  }
  clearInterval(syncTimer);
  syncTimer = setInterval(() => resync(false), 250);
  scheduleFlip();
}

export function pause() {
  elA?.pause();
  elB?.pause();
  player.playing = false;
  clearInterval(syncTimer);
  clearInterval(flipTimer);
}

export const toggle = () => (player.playing ? pause() : play());

export function switchTo(which) {
  if (which === player.active) return;
  const from = audible();
  player.position = aTimeOf(from);
  player.active = which;
  // Line the newly audible one up exactly before unmuting it.
  const to = audible();
  const want = timeFor(to, player.position);
  if (Math.abs(to.currentTime - want) > 0.03) to.currentTime = want;
  applyMute();
}

export const flip = () => switchTo(player.active === 'a' ? 'b' : 'a');

/** Seek both tracks; `which` also makes that track the audible one. */
export function seek(aTime, which = null) {
  player.position = Math.max(0, aTime);
  if (which) player.active = which;
  if (elA) {
    elA.currentTime = timeFor(elA, player.position);
    elB.currentTime = timeFor(elB, player.position);
    applyMute();
  }
}

function resync(force) {
  const lead = audible();
  const follow = silent();
  if (!lead) return;
  player.position = aTimeOf(lead);
  const want = timeFor(follow, player.position);
  if (force || Math.abs(follow.currentTime - want) > 0.06) follow.currentTime = want;
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
  if (elA) { elA.removeAttribute('src'); elB.removeAttribute('src'); elA.load(); elB.load(); }
  Object.assign(player, { loaded: false, a: null, b: null, position: 0, duration: 0 });
}
