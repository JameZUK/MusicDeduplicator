// Waveform peaks, fetched once per track and shared by every view. waveOf() is called
// from derived values, so it never writes state synchronously: results land when the
// fetch settles.
import { api } from './api.js';

const cache = $state({});      // path -> {status: 'ready', data} | {status: 'error', error}
const inflight = new Set();
const LOADING = Object.freeze({ status: 'loading' });

export function waveOf(path) {
  if (!path) return null;
  const hit = cache[path];
  if (hit) return hit;
  if (!inflight.has(path)) {
    inflight.add(path);
    api.waveform(path)
      .then((data) => { cache[path] = { status: 'ready', data }; })
      .catch((e) => { cache[path] = { status: 'error', error: e.message }; })
      .finally(() => inflight.delete(path));
  }
  return LOADING;
}
