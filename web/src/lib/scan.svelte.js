// Scan status, polled from the server: quickly while a scan runs, slowly otherwise
// (so a scan started from another device or at server start shows up too).
import { api } from './api.js';
import { store } from './store.svelte.js';

let timer = null;
let onFinished = () => {};

export function watchScans(finished) {
  onFinished = finished;
  poll();
}

async function poll() {
  clearTimeout(timer);
  let wasRunning = store.scan.state === 'running';
  try {
    store.scan = await api.scanState();
  } catch { /* keep the last state */ }
  if (wasRunning && store.scan.state !== 'running') onFinished(store.scan);
  timer = setTimeout(poll, store.scan.state === 'running' ? 1500 : 15000);
}

export async function startScan() {
  store.scan = await api.startScan();
  poll();
}

export async function stopScan() {
  await api.stopScan();
  poll();
}

/** Items per second and seconds left for the current stage (fingerprinting, comparing). */
export function eta(s) {
  if (!['fingerprinting', 'comparing'].includes(s.stage) || !s.done || !s.total) return null;
  const since = s.stage_started || s.started;
  const rate = s.done / Math.max(1, Date.now() / 1000 - since);
  return { rate, left: rate > 0 ? (s.total - s.done) / rate : 0 };
}
