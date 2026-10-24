import { api } from './api.js';

/** Polls a server job until it finishes; returns the finished job. */
export async function waitForJob(id, onUpdate = () => {}) {
  for (;;) {
    const job = await api.job(id);
    onUpdate(job);
    if (job.state !== 'running') return job;
    await new Promise((r) => setTimeout(r, 700));
  }
}

export function describeCounts(counts = {}) {
  const parts = Object.entries(counts).map(([k, v]) => `${v} ${k}`);
  return parts.length ? parts.join(', ') : 'nothing done';
}
