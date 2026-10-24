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

/** Files per second and seconds left for the fingerprinting stage. */
export function eta(s) {
  if (s.stage !== 'fingerprinting' || !s.done || !s.started) return null;
  const rate = s.done / (Date.now() / 1000 - s.started);
  return { rate, left: rate > 0 ? (s.total - s.done) / rate : 0 };
}
